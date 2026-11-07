import itertools
from datetime import date

import pytest

from algo.data.providers.nse_index_releases import PARSER_VERSION as V
from algo.data.universe import coverage_report, intervals
from algo.data.universe_build import add_override, derive, load_inputs, persist, voided
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
D = date
SECTION = itertools.count(1)  # the (doc, page, section, action, symbol) key must be unique


def doc(conn, doc_id, announced, kind="REPLACEMENT_TABLES"):
    label = "MANUAL_REVIEW_REQUIRED" if kind == "MANUAL_REVIEW" else "PARSED"
    conn.execute(
        "INSERT INTO index_release_document (doc_id,parser_version,announced,source_url,source_hash,"
        "kind,sections,notes,parsed_at,classification) VALUES (%s,%s,%s,'https://x/'||%s,"
        "'hash-'||%s,%s,'[]','[]',now(),%s)",
        (doc_id, V, announced, doc_id, doc_id, kind, label),
    )


def row(
    conn, doc_id, symbol, component, action, eff, iid=None, status="MAPPED", review="PROVISIONAL"
):
    conn.execute(
        "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,component,"
        "action,symbol,company,effective_from,raw_text,instrument_id,mapping_status,review_status)"
        " VALUES (%s,%s,1,%s,'s',%s,%s,%s,'',%s,'r',%s,%s,%s)",
        (doc_id, V, next(SECTION), component, action, symbol, eff, iid, status, review),
    )


@pytest.fixture
def world(conn):
    _, a, b = make_env(conn)
    doc(conn, "d1", D(2019, 2, 20))
    row(conn, "d1", "AAA", "MIDCAP_100", "INCLUDED", D(2019, 3, 29), a)
    row(conn, "d1", "BBB", "NIFTY_NEXT_50", "EXCLUDED", D(2019, 3, 29), b)
    row(conn, "d1", "AAA", "NIFTY_200", "INCLUDED", D(2019, 3, 29), a)
    row(conn, "d1", "BBB", "NIFTY_200", "EXCLUDED", D(2019, 3, 29), b)
    row(
        conn,
        "d1",
        "ZZZ",
        "NIFTY_50",
        "INCLUDED",
        D(2019, 3, 29),
        None,
        "UNMAPPED_SYMBOL",
        "REJECTED",
    )
    doc(conn, "m1", D(2018, 1, 5), "MANUAL_REVIEW")
    doc(conn, "old", D(2016, 1, 5), "MANUAL_REVIEW")  # before 2017: not our concern
    conn.execute("INSERT INTO index_snapshot VALUES ('NIFTY200','2026-11-06',%s)", (a,))
    return conn, a, b


def test_inputs_exclude_rejected_rows_and_old_manual_documents(world):
    conn, a, _ = world
    events, ids, manual, as_of, undated = load_inputs(conn)
    assert len(events) == 4 and ids == {a} and manual == ["m1"] and as_of == D(2026, 11, 6)
    assert undated == []
    assert {(e.key, e.component) for e in events if e.component == "MIDCAP_100"} == {
        (f"i:{a}", "MIDCAP_100")
    }


def test_undated_rows_are_surfaced_not_dropped(world):
    conn, a, _ = world
    conn.execute(
        "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,component,"
        "action,symbol,company,raw_text,instrument_id,mapping_status) VALUES ('d1',%s,1,999,'s',"
        "'MIDCAP_100','INCLUDED','AAA','','r',%s,'MAPPED')",
        (V, a),
    )
    report, _, _ = derive(conn)
    assert [d.symbol for d in report.of_kind("UNDATED_ROW")] == ["AAA"]


def test_a_consistent_history_reconciles_and_is_stored_provisional_without_coverage(world):
    conn, a, b = world
    report, snapshot, _ = derive(conn)
    assert report.of_kind("SNAPSHOT_MISMATCH") == [] and report.of_kind("CHECKPOINT_MISSING") == []
    assert report.gaps == {"MANUAL_DOCUMENT": 1, "METHODOLOGY_BOUNDARY": 1}
    assert persist(conn, report, snapshot, NOW) == 3  # initial member b, then a ADD and b REMOVE
    ivs = intervals(conn, "NIFTY200", strict=False)
    assert [(i.instrument_id, i.start, i.end) for i in ivs] == [
        (a, D(2019, 3, 29), None), (b, D(2018, 4, 2), D(2019, 3, 29)),
    ]  # fmt: skip
    rep = coverage_report(conn, "NIFTY200")
    assert rep["coverage"] == [] and rep["events"]["PROVISIONAL"] == 3 and not rep["strict_ready"]
    assert intervals(conn, "NIFTY200") == []  # strict mode sees nothing: nothing is verified


def test_instruments_that_do_not_reconcile_are_not_stored(world):
    conn, a, b = world
    conn.execute("DELETE FROM index_snapshot")
    conn.execute(
        "INSERT INTO index_snapshot VALUES ('NIFTY200','2026-11-06',%s)", (b,)
    )  # a vanished
    report, snapshot, _ = derive(conn)
    assert {d.key for d in report.of_kind("SNAPSHOT_MISMATCH")} == {f"i:{a}", f"i:{b}"}
    assert persist(conn, report, snapshot, NOW) == 1  # only the initial-state member is written


def test_a_missing_snapshot_is_an_error(conn):
    make_env(conn)
    with pytest.raises(ValueError, match="no current Nifty 200 snapshot"):
        load_inputs(conn)


def test_a_voided_release_never_enters_the_derivation_but_stays_visible(world):
    conn, a, b = world
    add_override(conn, doc_id="d1", effective_from=D(2019, 3, 29), authority_doc="d9",
                 authority_quote="shall stand null and void", now=NOW)  # fmt: skip
    add_override(conn, doc_id="d1", effective_from=D(2019, 3, 29), authority_doc="d9",
                 authority_quote="shall stand null and void", now=NOW)  # idempotent  # fmt: skip
    events, *_ = load_inputs(conn)
    assert events == []  # every d1 row was announced for the voided date
    v = voided(conn)
    assert {(x[0], x[1], x[3], x[4], x[5]) for x in v} >= {
        ("AAA", "MIDCAP_100", "d1", "2019-03-29", "d9")
    }
    assert len(v) == 5  # four component rows and the rejected one: voiding is by release + date
    report, _, _ = derive(conn)
    assert len(report.of_kind("VOIDED_ROW")) == len(v) and report.derived == []


def test_component_lists_are_loaded_and_checked_against_each_components_own_history(world):
    from algo.data.universe_build import load_component_snapshots

    conn, a, b = world
    assert load_component_snapshots(conn) == {}  # no component list stored yet
    conn.execute(
        "INSERT INTO index_snapshot VALUES ('NIFTYMIDCAP100','2026-11-01',%s)", (b,)
    )  # older
    conn.execute("INSERT INTO index_snapshot VALUES ('NIFTYMIDCAP100','2026-11-07',%s)", (a,))
    conn.execute("INSERT INTO index_snapshot VALUES ('NIFTYNEXT50','2026-11-07',%s)", (b,))
    assert load_component_snapshots(conn) == {
        "MIDCAP_100": {a},
        "NIFTY_NEXT_50": {b},
    }  # latest only
    report, _, _ = derive(conn)
    # a: Midcap 100 INCLUDED and the list agrees; b: Next 50 EXCLUDED but the list says member
    got = [(d.symbol, d.detail) for d in report.of_kind("COMPONENT_SNAPSHOT_MISMATCH")]
    assert got == [
        ("BBB", "NIFTY_NEXT_50: last event is EXCLUDED but the current list says member")
    ]


def test_monthly_snapshots_reconcile_against_release_events_with_identity_kept(world):
    from algo.data.providers.nse_index_monthly import PARSER_VERSION as MV
    from algo.data.universe_build import load_monthly_snapshots, monthly_events, reconcile_monthly

    conn, a, b = world

    def snapshot(component, as_of, rows):
        sid = conn.execute(
            "INSERT INTO index_monthly_snapshot (index_name,component,as_of,zip_hash,pdf_name,pdf_hash,"
            "parser_version,problems,parsed_at) VALUES ('n',%s,%s,'z','p','h',%s,'[]',now())"
            " RETURNING snapshot_id", (component, as_of, MV)).fetchone()[0]  # fmt: skip
        for iid, sym in rows:
            conn.execute("INSERT INTO index_monthly_constituent VALUES (%s,%s,'n','i',1,1,1,1,%s,%s)",
                         (sid, sym, iid, "MAPPED" if iid else "UNMAPPED_SYMBOL"))  # fmt: skip

    snapshot("MIDCAP_100", D(2019, 2, 28), [(b, "BBB")])
    snapshot("MIDCAP_100", D(2019, 3, 29), [(a, "AAA"), (None, "GONEX")])  # AAA joined 2019-03-29
    snaps = load_monthly_snapshots(conn)
    assert {(s.component, s.as_of): dict(s.members) for s in snaps} == {
        ("MIDCAP_100", D(2019, 2, 28)): {f"i:{b}": "BBB"},
        ("MIDCAP_100", D(2019, 3, 29)): {f"i:{a}": "AAA", "s:GONEX": "GONEX"},
    }
    assert [e.key for e in monthly_events(conn)].count(f"i:{a}") == 2  # MIDCAP_100 + NIFTY_200 rows
    _, diffs = reconcile_monthly(conn)
    got = {(d.kind, d.key, d.component) for d in diffs}
    assert ("UNEXPLAINED_ADD", "s:GONEX", "MIDCAP_100") in got  # visible even though unresolved
    assert ("UNEXPLAINED_ADD", f"i:{a}", "MIDCAP_100") not in got  # the INCLUDED event explains it
    assert ("UNEXPLAINED_REMOVE", f"i:{b}", "MIDCAP_100") in got  # b left, no event says so


def test_a_symbol_has_one_identity_whatever_date_each_source_was_resolved_at(world):
    from algo.data.universe_build import symbol_identity

    conn, a, b = world
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','LATE',NULL,'2030-01-01',NULL)", (a,)
    )
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','REUSED',NULL,'2000-01-01','2010-01-01')",
        (a,),
    )
    conn.execute(
        "INSERT INTO instrument_alias VALUES (%s,'nse','REUSED',NULL,'2012-01-01',NULL)", (b,)
    )
    ident = symbol_identity(conn)
    assert ident["LATE"] == a  # valid only from 2030, yet it names this instrument at any date
    assert "REUSED" not in ident  # two companies used it: the date decides, so no shortcut

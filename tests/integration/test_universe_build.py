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

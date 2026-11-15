from datetime import UTC, date, datetime

import pytest

from algo.data.identity_application import IdentityApplicationError, apply_historical_instrument
from algo.data.index_monthly import remap_monthly
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 10, tzinfo=UTC)
TARGETS = {"GUJENERGY": "INE844O01030"}


def app(**over):
    base = {
        "item_id": "symbol:GSPL", "decision_id": 12, "name": "Gujarat State Petronet Limited",
        "instrument": {"symbol": "GSPL", "isin": "INE246F01010", "status": "delisted", "listed_on": None,
                       "first_observed_on": "2006-02-16", "last_traded_on": "2026-05-11", "delisted_on": None},
        "alias": {"source": "nse", "source_symbol": "GSPL", "valid_from": "2006-02-16", "valid_from_basis": "FIRST_OBSERVED",
                  "valid_to": "2026-05-12", "valid_to_basis": "LAST_OBSERVED"},
        "relationship": {"relationship_type": "AMALGAMATED_INTO", "target_symbol": "GUJENERGY", "appointed_date": None,
                         "effective_date": "2026-05-01", "ratio_num": 10, "ratio_den": 13, "known_at": None,
                         "evidence": ["NSE press release (read)"], "verification_status": "PROVISIONAL", "review_decision_id": 12},
    }  # fmt: skip
    base.update(over)
    return base


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    target = repo.add_instrument(x, "GUJENERGY", isin="INE844O01030")
    repo.add_alias(target, "nse", "GUJENERGY", date(2026, 7, 1))
    other = repo.add_instrument(
        x, "GNRL", isin="INE207H01026"
    )  # a DIFFERENT company: must stay untouched
    repo.add_alias(other, "nse", "GNRL", date(2026, 4, 20))
    conn.execute(
        "INSERT INTO review_decision (item_id, decision, effective_date, evidence_ref, note, reviewer, decided_at)"
        " VALUES ('symbol:GSPL','KEEP_SEPARATE',NULL,'e','n','tester',%s)", (NOW,))  # fmt: skip
    decision_id = conn.execute("SELECT max(decision_id) FROM review_decision").fetchone()[0]
    return conn, target, other, decision_id


def run(env, **over):
    conn, _, _, did = env
    a = app(decision_id=did, **over)
    a["relationship"] = {**a["relationship"], "review_decision_id": did}
    return apply_historical_instrument(conn, a, TARGETS, NOW)


def test_it_creates_one_historical_instrument_its_alias_and_the_relationship_and_nothing_else(env):
    conn, target, other, did = env
    before = {
        t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("instrument", "instrument_alias", "corporate_action_relationship", "bar_1d")
    }  # noqa: S608
    r = run(env)
    after = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
    assert {t: after[t] - before[t] for t in before} == {
        "instrument": 1,
        "instrument_alias": 1,
        "corporate_action_relationship": 1,
        "bar_1d": 0,
    }
    row = conn.execute("SELECT symbol, isin, name, status, listed_on, delisted_on, first_observed_on, last_traded_on, exchange_id, quote_currency, asset_class FROM instrument WHERE instrument_id=%s", (r.instrument_id,)).fetchone()  # fmt: skip
    tx = conn.execute(
        "SELECT exchange_id, quote_currency FROM instrument WHERE instrument_id=%s", (target,)
    ).fetchone()
    assert row == ("GSPL", "INE246F01010", "Gujarat State Petronet Limited", "delisted", None, None, date(2006, 2, 16), date(2026, 5, 11), tx[0], tx[1], "equity")  # fmt: skip
    al = conn.execute("SELECT instrument_id, source, source_symbol, valid_from, valid_from_basis, valid_to, valid_to_basis FROM instrument_alias WHERE instrument_id=%s", (r.instrument_id,)).fetchall()  # fmt: skip
    assert al == [
        (
            r.instrument_id,
            "nse",
            "GSPL",
            date(2006, 2, 16),
            "FIRST_OBSERVED",
            date(2026, 5, 12),
            "LAST_OBSERVED",
        )
    ]
    rel = conn.execute("SELECT relationship_type, source_instrument_id, target_instrument_id, target_symbol, effective_date, last_source_session, ratio_num, ratio_den, verification_status, review_decision_id FROM corporate_action_relationship").fetchone()  # fmt: skip
    assert rel == ("AMALGAMATED_INTO", r.instrument_id, target, "GUJENERGY", date(2026, 5, 1), date(2026, 5, 11), 10, 13, "PROVISIONAL", did)  # fmt: skip
    # the unrelated company with a similar-looking successor name is untouched, and the target is unchanged
    assert (
        conn.execute(
            "SELECT count(*) FROM instrument_alias WHERE instrument_id=%s", (other,)
        ).fetchone()[0]
        == 1
    )
    assert conn.execute(
        "SELECT status, delisted_on FROM instrument WHERE instrument_id=%s", (target,)
    ).fetchone() == ("active", None)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"decision_id": 999}, "no KEEP_SEPARATE review decision"),
        ({"item_id": "symbol:OTHER"}, "no KEEP_SEPARATE review decision"),
    ],
)
def test_it_refuses_without_the_recorded_keep_separate_decision(env, over, message):
    conn, _, _, did = env
    a = app(decision_id=did)
    a.update(over)
    with pytest.raises(IdentityApplicationError, match=message):
        apply_historical_instrument(conn, a, TARGETS, NOW)
    assert conn.execute("SELECT count(*) FROM corporate_action_relationship").fetchone()[0] == 0


def test_it_refuses_a_target_that_is_missing_or_has_a_different_isin(env):
    conn, _, _, did = env
    rel = app(decision_id=did)["relationship"]
    with pytest.raises(IdentityApplicationError, match="not in the reviewed targets"):
        run(env, relationship={**rel, "target_symbol": "GNRLX"})
    with pytest.raises(IdentityApplicationError, match="target GONE does not exist"):
        apply_historical_instrument(
            conn,
            app(decision_id=did, relationship={**rel, "target_symbol": "GONE"}),
            {"GONE": "INE000000000"},
            NOW,
        )
    with pytest.raises(
        IdentityApplicationError, match="ISIN INE207H01026 which is not the reviewed INE844O01030"
    ):
        apply_historical_instrument(
            conn,
            app(decision_id=did, relationship={**rel, "target_symbol": "GNRL"}),
            {"GNRL": "INE844O01030"},
            NOW,
        )
    assert conn.execute("SELECT count(*) FROM instrument").fetchone()[0] == 2


def test_it_refuses_a_second_application_and_an_isin_or_symbol_already_present(env):
    conn, target, other, did = env
    run(env)
    with pytest.raises(
        IdentityApplicationError, match="ISIN INE246F01010 already has an instrument"
    ):
        run(env)
    assert (
        conn.execute("SELECT count(*) FROM instrument WHERE isin='INE246F01010'").fetchone()[0] == 1
    )
    inst = app(decision_id=did)["instrument"]
    with pytest.raises(IdentityApplicationError, match="alias nse:GSPL overlaps"):
        run(env, instrument={**inst, "isin": "INE246F01099"})  # new ISIN, same symbol and dates


def test_it_refuses_an_alias_that_does_not_belong_to_the_instrument_or_ends_before_it_starts(env):
    conn, _, _, did = env
    al = app(decision_id=did)["alias"]
    with pytest.raises(
        IdentityApplicationError, match="alias symbol must equal the instrument symbol"
    ):
        run(env, alias={**al, "source_symbol": "GNRL"})
    with pytest.raises(IdentityApplicationError, match="alias must end after the last traded day"):
        run(env, alias={**al, "valid_to": "2026-05-11"})
    assert (
        conn.execute("SELECT count(*) FROM instrument WHERE isin='INE246F01010'").fetchone()[0] == 0
    )


def test_the_whole_application_rolls_back_if_a_later_step_fails(env):
    conn, _, _, did = env
    rel = app(decision_id=did)["relationship"]
    with pytest.raises(Exception, match="violates check constraint"):
        run(
            env, relationship={**rel, "ratio_den": None}
        )  # ratio_num without ratio_den: the table's CHECK
    assert (
        conn.execute("SELECT count(*) FROM instrument WHERE isin='INE246F01010'").fetchone()[0] == 0
    )
    assert (
        conn.execute("SELECT count(*) FROM instrument_alias WHERE source_symbol='GSPL'").fetchone()[
            0
        ]
        == 0
    )


def test_monthly_constituents_map_to_the_instrument_once_its_alias_exists_with_the_same_day_rule(
    env,
):
    conn, target, other, did = env
    snap = conn.execute(
        "INSERT INTO index_monthly_snapshot (index_name,component,as_of,zip_hash,pdf_name,pdf_hash,parser_version,problems,parsed_at)"
        " VALUES ('NIFTY 100','N100x','2021-06-30','z','p','h','2','[]',%s) RETURNING snapshot_id", (NOW,)).fetchone()[0]  # fmt: skip
    for sym in ("GSPL", "NOSUCH"):
        conn.execute(
            "INSERT INTO index_monthly_constituent VALUES (%s,%s,'n','i',1,1,1,1,NULL,'UNMAPPED_SYMBOL')",
            (snap, sym),
        )
    assert remap_monthly(conn) == 0  # no alias yet: nothing to map
    r = run(env)
    assert remap_monthly(conn) == 1
    rows = dict(
        conn.execute(
            "SELECT symbol, (instrument_id, mapping_status)::text FROM index_monthly_constituent"
        ).fetchall()
    )
    assert rows == {"GSPL": f"({r.instrument_id},MAPPED)", "NOSUCH": "(,UNMAPPED_SYMBOL)"}
    assert remap_monthly(conn) == 0  # idempotent
    late = conn.execute(
        "INSERT INTO index_monthly_snapshot (index_name,component,as_of,zip_hash,pdf_name,pdf_hash,parser_version,problems,parsed_at)"
        " VALUES ('NIFTY 100','N100x','2026-05-29','z','p','h2','2','[]',%s) RETURNING snapshot_id", (NOW,)).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO index_monthly_constituent VALUES (%s,'GSPL','n','i',1,1,1,1,NULL,'UNMAPPED_SYMBOL')",
        (late,),
    )
    assert (
        remap_monthly(conn) == 0
    )  # the alias ended on 2026-05-12: a May-29 row stays unmapped, never guessed


def test_remap_can_be_limited_to_the_symbols_of_one_application(env):
    from algo.data.index_releases import remap

    conn, target, other, did = env
    repo = InstrumentRepo(conn)
    x = conn.execute("SELECT exchange_id FROM exchange LIMIT 1").fetchone()[0]
    older = repo.add_instrument(x, "OLDCO", isin="INE111A01011")
    repo.add_alias(
        older, "nse", "OLDCO", date(2000, 1, 1)
    )  # an alias that already existed: its rows are stale
    snap = conn.execute(
        "INSERT INTO index_monthly_snapshot (index_name,component,as_of,zip_hash,pdf_name,pdf_hash,parser_version,problems,parsed_at)"
        " VALUES ('NIFTY 100','N100x','2021-06-30','z','p','h','2','[]',%s) RETURNING snapshot_id", (NOW,)).fetchone()[0]  # fmt: skip
    conn.execute(
        "INSERT INTO index_release_document (doc_id,parser_version,announced,source_url,source_hash,kind,sections,notes,parsed_at,classification,classification_reason,extracted_text)"
        " VALUES ('d','7',DATE '2021-06-30','u','h','k','[]','[]',%s,'PARSED','r','t')", (NOW,))  # fmt: skip
    for sym in ("GSPL", "OLDCO"):
        conn.execute(
            "INSERT INTO index_monthly_constituent VALUES (%s,%s,'n','i',1,1,1,1,NULL,'UNMAPPED_SYMBOL')",
            (snap, sym),
        )
        conn.execute(
            "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,component,action,symbol,company,"
            "effective_from,related_symbol,raw_text,instrument_id,mapping_status,review_status)"
            " VALUES ('d','7',1,1,'s','NIFTY_200','INCLUDED',%s,'c',DATE '2021-06-30',NULL,'t',NULL,'UNMAPPED_SYMBOL','PROVISIONAL')", (sym,))  # fmt: skip
    run(env)
    assert (remap(conn, ["GSPL"]), remap_monthly(conn, ["GSPL"])) == (1, 1)  # only GSPL
    left = conn.execute(
        "SELECT symbol FROM index_monthly_constituent WHERE mapping_status='UNMAPPED_SYMBOL'"
    ).fetchall()
    assert left == [("OLDCO",)]  # the stale OLDCO row was NOT swept along
    assert (
        conn.execute(
            "SELECT count(*) FROM index_release_row WHERE mapping_status='UNMAPPED_SYMBOL'"
        ).fetchone()[0]
        == 1
    )
    assert (remap(conn), remap_monthly(conn)) == (1, 1)  # unrestricted keeps its old behaviour


def hexaware(**over):
    base = {
        "item_id": "symbol:HEXAWARE", "name": "Hexaware Technologies Limited", "reference_symbol": "GUJENERGY",
        "instrument": {"symbol": "HEXAWARE", "isin": "INE093A01033", "status": "delisted", "listed_on": None,
                       "first_observed_on": "2002-06-14", "last_traded_on": "2020-10-30", "delisted_on": "2020-11-09"},
        "alias": {"source": "nse", "source_symbol": "HEXAWARE", "valid_from": "2002-06-14", "valid_from_basis": "FIRST_OBSERVED",
                  "valid_to": "2020-10-31", "valid_to_basis": "LAST_OBSERVED"},
        "relationship": None,
    }  # fmt: skip
    base.update(over)
    return base


def decide(conn, item, decision):
    conn.execute(
        "INSERT INTO review_decision (item_id, decision, effective_date, evidence_ref, note, reviewer, decided_at)"
        " VALUES (%s,%s,NULL,'e','n','tester',%s)", (item, decision, NOW))  # fmt: skip
    return conn.execute("SELECT max(decision_id) FROM review_decision").fetchone()[0]


def test_a_company_with_no_successor_gets_an_instrument_and_an_alias_and_no_relationship(env):
    conn, target, other, _ = env
    did = decide(conn, "symbol:HEXAWARE", "NO_SUCCESSOR")
    before = conn.execute("SELECT count(*) FROM corporate_action_relationship").fetchone()[0]
    r = apply_historical_instrument(conn, hexaware(decision_id=did), TARGETS, NOW)
    assert (r.relationship_id, r.target_instrument_id) == (None, None)
    assert (
        conn.execute("SELECT count(*) FROM corporate_action_relationship").fetchone()[0] == before
    )  # none written
    row = conn.execute("SELECT symbol, isin, status, delisted_on, last_traded_on, exchange_id, quote_currency FROM instrument WHERE instrument_id=%s", (r.instrument_id,)).fetchone()  # fmt: skip
    ref = conn.execute(
        "SELECT exchange_id, quote_currency FROM instrument WHERE instrument_id=%s", (target,)
    ).fetchone()
    assert row == (
        "HEXAWARE",
        "INE093A01033",
        "delisted",
        date(2020, 11, 9),
        date(2020, 10, 30),
        ref[0],
        ref[1],
    )
    assert conn.execute("SELECT valid_from, valid_to FROM instrument_alias WHERE instrument_id=%s", (r.instrument_id,)).fetchall() == [(date(2002, 6, 14), date(2020, 10, 31))]  # fmt: skip


def test_the_decision_must_match_the_kind_of_application(env):
    conn, *_ = env
    keep = decide(
        conn, "symbol:HEXAWARE", "KEEP_SEPARATE"
    )  # a successor was decided, but the application says there is none
    with pytest.raises(IdentityApplicationError, match="no NO_SUCCESSOR review decision"):
        apply_historical_instrument(conn, hexaware(decision_id=keep), TARGETS, NOW)
    none = decide(
        conn, "symbol:GSPL", "NO_SUCCESSOR"
    )  # no successor was decided, but the application names one
    wrong = app(decision_id=none)
    wrong["relationship"] = {**wrong["relationship"], "review_decision_id": none}
    with pytest.raises(IdentityApplicationError, match="no KEEP_SEPARATE review decision"):
        apply_historical_instrument(conn, wrong, TARGETS, NOW)


def test_an_application_without_a_successor_needs_a_reference_stock_that_exists(env):
    conn, *_ = env
    did = decide(conn, "symbol:HEXAWARE", "NO_SUCCESSOR")
    with pytest.raises(IdentityApplicationError, match="reference_symbol"):
        apply_historical_instrument(
            conn, hexaware(decision_id=did, reference_symbol=None), TARGETS, NOW
        )
    with pytest.raises(IdentityApplicationError, match="does not exist"):
        apply_historical_instrument(
            conn, hexaware(decision_id=did, reference_symbol="NOSUCH"), TARGETS, NOW
        )

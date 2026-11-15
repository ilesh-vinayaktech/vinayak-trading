from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.data.adjust.factors import build_adjustments, factor_on
from algo.data.corporate_actions import (
    PROXY,
    knowledge_time_for,
    load_actions,
    new_unresolved,
    records_for,
    review_keys,
)
from algo.data.providers.nse_corporate_actions import parse_actions
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
RAW = (Path(__file__).parents[1] / "data/nse/corporate_actions_sample.json").read_bytes()  # real
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
SYMS = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ITC",
    "WIPRO",
    "BAJFINANCE",
    "ICICIBANK",
    "ASIANPAINT",
]


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for s in SYMS:
        ids[s] = repo.add_instrument(x, s)
        repo.add_alias(ids[s], "nse", s, date(1990, 1, 1))
    return conn, ids


def test_knowledge_time_is_start_of_ex_date_ist():
    assert knowledge_time_for(date(2025, 6, 16)) == datetime(2025, 6, 15, 18, 30, tzinfo=UTC)


def test_load_is_idempotent_and_records_proxy_knowledge_time(env):
    conn, ids = env
    acts, _ = parse_actions(RAW)
    r1 = load_actions(conn, acts, "sum", NOW)
    assert r1.inserted > 0 and r1.unknown_symbols == ["SHARDUL"]  # buy-back row, not seeded
    r2 = load_actions(conn, acts, "sum", NOW)
    assert r2.inserted == 0 and r2.unchanged == r1.inserted + r1.unchanged
    n = conn.execute("SELECT count(*) FROM corporate_action").fetchone()[0]
    assert n == r1.inserted
    row = conn.execute(
        "SELECT knowledge_time, knowledge_time_source, announced_at FROM corporate_action "
        "WHERE instrument_id=%s AND kind='bonus' AND ex_date='2024-10-28'",
        (ids["RELIANCE"],),
    ).fetchone()
    assert row == (datetime(2024, 10, 27, 18, 30, tzinfo=UTC), PROXY, None)


def test_unknown_symbol_reported_not_loaded(conn):
    migrate(conn)
    acts, _ = parse_actions(RAW)
    r = load_actions(conn, acts, "sum", NOW)
    assert r.inserted == 0 and "RELIANCE" in r.unknown_symbols


def test_alias_validity_respected(env):
    conn, _ = env
    acts, _ = parse_actions(RAW)
    conn.execute(
        "UPDATE instrument_alias SET valid_from='2020-01-01' WHERE source_symbol='RELIANCE'"
    )
    r = load_actions(conn, acts, "sum", NOW)
    assert "RELIANCE" in r.unknown_symbols  # 2009/2017 actions precede the alias


def test_end_to_end_reliance_factors_from_real_actions(env):
    """Reliance real history: bonus 1:1 2009, 2017, 2024 (+ rights/demerger held for review)."""
    conn, ids = env
    load_actions(conn, parse_actions(RAW)[0], "sum", NOW)
    built = build_adjustments(records_for(conn, ids["RELIANCE"]), lambda d: D(1000))
    kinds = sorted({u.kind for u in built.unapplied})  # review items surface
    assert {"rights", "demerger"} <= set(kinds)  # not applied: need a human
    # three 1:1 bonuses => a bar before 2009 is scaled by 1/2^3
    assert factor_on(built.adjustments, date(2009, 1, 1)) == D("0.125")
    assert factor_on(built.adjustments, date(2018, 1, 1)) == D("0.5")  # only the 2024 bonus after
    assert factor_on(built.adjustments, date(2024, 10, 28)) == 1
    # point-in-time: the 2024 bonus is not yet known the day before its ex-date
    asof = datetime(2024, 10, 20, tzinfo=UTC)
    assert factor_on(built.adjustments, date(2018, 1, 1), as_of=asof) == 1


def test_bajaj_2025_bonus_plus_split_from_real_rows(env):
    conn, ids = env
    load_actions(conn, parse_actions(RAW)[0], "sum", NOW)
    built = build_adjustments(records_for(conn, ids["BAJFINANCE"]), lambda d: D(1000))
    assert factor_on(built.adjustments, date(2025, 6, 13)) == D("0.1")  # (1/5) * (1/2)


def _fake_api(url):
    """Mimic NSE: returns only the requested symbol's rows."""
    import json
    from urllib.parse import parse_qs, urlparse

    sym = parse_qs(urlparse(url).query)["symbol"][0]
    return json.dumps([r for r in json.loads(RAW) if r["symbol"] == sym]).encode()


def test_ingest_symbol_stores_raw_loads_actions_and_is_idempotent(env, tmp_path):
    from algo.data.corporate_actions import ingest_symbol
    from algo.data.lake import LocalLake

    conn, ids = env
    lake = LocalLake(tmp_path)
    r1 = ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW)
    assert r1 is not None and r1.inserted > 0
    assert len(lake.versions("nse", "corporate_actions_BAJFINANCE", NOW.date())) == 1
    r2 = ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW)  # replaces, never duplicates
    assert (r2.inserted, r2.replaced) == (r1.inserted, r1.inserted)
    n = conn.execute(
        "SELECT count(*) FROM corporate_action WHERE instrument_id=%s", (ids["BAJFINANCE"],)
    ).fetchone()[0]
    assert n == r1.inserted
    assert ingest_symbol(conn, lake, _fake_api, "NOSUCH", NOW) is None


def test_ingest_uses_issuer_not_alias_validity_for_renamed_stocks(env, tmp_path):
    """Feed rows carry the CURRENT symbol even for pre-rename ex-dates; alias-by-date would miss."""
    from algo.data.corporate_actions import ingest_symbol
    from algo.data.lake import LocalLake

    conn, ids = env
    conn.execute(
        "UPDATE instrument_alias SET valid_from='2025-01-01' WHERE source_symbol='RELIANCE'"
    )
    r = ingest_symbol(conn, LocalLake(tmp_path), _fake_api, "RELIANCE", NOW)
    assert r.unknown_symbols == [] and r.inserted > 0  # 2009 / 2017 actions still loaded


def test_reparse_from_lake_applies_improved_parser_without_network(env, tmp_path):
    from algo.data.corporate_actions import ingest_symbol, reparse_symbol
    from algo.data.lake import LocalLake

    conn, ids = env
    lake = LocalLake(tmp_path)
    assert reparse_symbol(conn, lake, "BAJFINANCE", NOW) is None  # nothing fetched yet
    ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW)
    # simulate rows produced by an older, weaker parser: a real bonus stuck in review
    conn.execute(
        "UPDATE corporate_action SET status='review', num=NULL, den=NULL, reason='old parser' "
        "WHERE instrument_id=%s AND kind='bonus'",
        (ids["BAJFINANCE"],),
    )
    r = reparse_symbol(conn, lake, "BAJFINANCE", NOW)
    assert r.replaced == r.inserted > 0
    bonus = conn.execute(
        "SELECT status, num, den FROM corporate_action WHERE instrument_id=%s AND kind='bonus' "
        "ORDER BY ex_date",
        (ids["BAJFINANCE"],),
    ).fetchall()
    assert bonus and all(b[0] == "ok" and b[1] and b[2] for b in bonus)
    assert reparse_symbol(conn, lake, "NOSUCH", NOW) is None


def test_replace_is_scoped_to_one_issuer(env, tmp_path):
    from algo.data.corporate_actions import ingest_symbol
    from algo.data.lake import LocalLake

    conn, ids = env
    lake = LocalLake(tmp_path)
    ingest_symbol(conn, lake, _fake_api, "RELIANCE", NOW)
    q = "SELECT count(*) FROM corporate_action WHERE instrument_id=%s"
    before = conn.execute(q, (ids["RELIANCE"],)).fetchone()[0]
    ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW)
    assert conn.execute(q, (ids["RELIANCE"],)).fetchone()[0] == before


# --- a refresh tells you about NEW items that need a person, and only those ---
def test_only_review_items_that_are_new_and_unresolved_are_reported(env):
    from algo.data.review import resolve

    conn, ids = env
    acts, _ = parse_actions(RAW)
    early = [a for a in acts if a.ex_date < date(2020, 1, 1)]
    load_actions(conn, early, "sum", NOW)
    before = review_keys(conn)
    assert before  # the old dividends in percent are already waiting for a person
    load_actions(conn, acts, "sum", NOW)  # the refresh brings the later actions
    found = {(sym, str(ex), kind) for sym, ex, kind, _subject in new_unresolved(conn, before)}
    assert found == {  # the old items were already waiting; these three are what the refresh added
        ("RELIANCE", "2020-05-13", "rights"),
        ("RELIANCE", "2023-07-20", "demerger"),
        ("ITC", "2025-01-06", "demerger"),
    }
    # a person decides one: it stops being reported
    resolve(
        conn,
        symbol="ITC",
        ex_date=date(2025, 1, 6),
        kind="demerger",
        method="ignore",
        note="test",
        by="t",
        now=NOW,
    )
    left = {(sym, kind) for sym, _ex, kind, _s in new_unresolved(conn, before)}
    assert ("ITC", "demerger") not in left and ("RELIANCE", "demerger") in left


def test_rebuilding_an_issuers_rows_does_not_make_old_items_look_new(env):
    conn, _ = env
    acts, _ = parse_actions(RAW)
    load_actions(conn, acts, "sum", NOW)
    before = review_keys(conn)
    conn.execute(
        "DELETE FROM corporate_action"
    )  # what a refresh does per issuer: the ids all change
    load_actions(conn, acts, "sum", NOW)
    assert new_unresolved(conn, before) == []


# ---- a symbol whose alias has ended (a stock that merged or delisted) ------------------------------------------------------
def test_a_symbol_whose_alias_has_ended_is_skipped_unless_asked_for_by_name(env, tmp_path):
    from algo.data.corporate_actions import ingest_symbol, reparse_symbol
    from algo.data.lake import LocalLake

    conn, ids = env
    lake = LocalLake(tmp_path)
    conn.execute(
        "UPDATE instrument_alias SET valid_to='2025-01-01' WHERE source_symbol='BAJFINANCE'"
    )
    assert (
        ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW) is None
    )  # the daily job never sees it
    r = ingest_symbol(conn, lake, _fake_api, "BAJFINANCE", NOW, include_ended=True)
    assert r is not None and r.inserted > 0
    assert conn.execute(
        "SELECT count(DISTINCT instrument_id) FROM corporate_action WHERE instrument_id=%s",
        (ids["BAJFINANCE"],),
    ).fetchone() == (1,)
    assert reparse_symbol(conn, lake, "BAJFINANCE", NOW) is None  # default behaviour unchanged
    again = reparse_symbol(conn, lake, "BAJFINANCE", NOW, include_ended=True)
    assert again is not None and again.inserted == r.inserted


def test_a_symbol_that_belongs_to_two_instruments_is_refused_not_guessed(env, tmp_path):
    from algo.data.corporate_actions import ingest_symbol
    from algo.data.lake import LocalLake
    from algo.data.store.instruments import InstrumentRepo

    conn, _ = env
    conn.execute(
        "UPDATE instrument_alias SET valid_to='2024-01-01' WHERE source_symbol='BAJFINANCE'"
    )
    repo = InstrumentRepo(conn)
    other = repo.add_instrument(
        conn.execute("SELECT exchange_id FROM exchange WHERE mic='XNSE'").fetchone()[0],
        "BAJFINANCE2",
    )
    repo.add_alias(other, "nse", "BAJFINANCE", date(2024, 1, 2), date(2025, 6, 30))
    with pytest.raises(ValueError, match="more than one instrument"):
        ingest_symbol(conn, LocalLake(tmp_path), _fake_api, "BAJFINANCE", NOW, include_ended=True)

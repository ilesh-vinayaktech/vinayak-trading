"""The daily paper runner with a screener strategy: the screen is checked every session. ENGINEERING_TEST_ONLY: synthetic prices."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.amfi_caps import CapList, CapRow
from algo.data.market_caps import load_list
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, configs
from algo.paper.runner import run_day
from tests.support.filings import add_filings
from tests.support.market import NOW, put, put_path, sessions
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
SCREEN = {
    "screen": {
        "conditions": [{"field": "chg_1m", "op": "gt", "value": 0}],
        "match": "all",
        "sort": "chg_1m",
        "descending": True,
    },
    "segments": ["large", "mid"],
}
JAN = date(2025, 1, 1)
DAYS = sessions(520)
CRASH = DAYS.index(date(2025, 1, 8))  # SLOW halves on this session, then rises again


def at(day):
    return datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=13)


@pytest.fixture
def env(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "kite")
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    names = ("FAST", "SLOW", "EXTRA", "FALLING")
    ids = {s: repo.add_instrument(x, s, isin=f"INE00000000{i}") for i, s in enumerate(names, 1)}
    put(conn, ids["FAST"], "0.004", DAYS)
    put(conn, ids["EXTRA"], "0.001", DAYS)
    put(conn, ids["FALLING"], "-0.002", DAYS)
    put_path(conn, ids["SLOW"], DAYS, [(CRASH - 1, "0.002"), (1, "-0.5"), (1, "0.002")])
    rows = tuple(
        CapRow(i, f"INE00000000{i}", s, f"Co {i}", D(1000 - i)) for i, s in enumerate(names, 1)
    )
    load_list(conn, CapList(date(2023, 6, 30), rows), "u1", "s1", NOW)
    uid = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    book.create_account(
        conn, uid, strategy_id="trend_pullback", params={}, initial_cash=D(1_000_000),
        started_on=JAN, now=NOW,
    )  # fmt: skip
    cid = configs.create(
        conn, uid, name="Rising", universe=configs.SEGMENTS, max_instruments=None, timeframe="1D",
        params={"max_positions": 5}, now=NOW, strategy_id="screener", screen=SCREEN,
    )  # fmt: skip
    configs.use(conn, uid, cid)
    return conn, ids, uid, tmp_path


def hold(conn, uid, iid, qty=100):
    book.record_fill(
        conn, uid, day=JAN, side="BUY", iid=iid, qty=D(qty), price=D(100), commission=D(0),
        charges=[], ref=f"seed{iid}", now=NOW,
    )  # fmt: skip


def orders(conn, uid, day):
    sql = "SELECT instrument_id, side, qty, reason FROM paper_order WHERE user_id=%s AND decision_day=%s ORDER BY instrument_id"
    return conn.execute(sql, (uid, day)).fetchall()


def test_using_a_screener_strategy_puts_its_rules_on_the_account(env):
    conn, _, uid, _ = env
    acct = book.get_account(conn, uid)
    assert acct["strategy_id"] == "screener" and acct["universe"] == configs.SEGMENTS
    assert acct["params"] == {"max_positions": 5} and acct["screen"] == SCREEN
    back = configs.create(
        conn, uid, name="Trend", universe="nifty100", max_instruments=None, timeframe="1D",
        params={"trend_sma": 200, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 10}, now=NOW,
    )  # fmt: skip
    configs.use(conn, uid, back)
    acct = book.get_account(conn, uid)
    assert acct["strategy_id"] == "trend_pullback" and acct["screen"] is None


def test_every_stock_that_matches_is_proposed_for_buying_and_waits_for_approval(env):
    conn, ids, uid, lake = env
    out = run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    assert out.status == "PROPOSED", out.detail
    rows = orders(conn, uid, JAN)
    assert [r[0] for r in rows] == [
        ids["FAST"],
        ids["SLOW"],
        ids["EXTRA"],
    ]  # the faller never matches
    assert all(r[1] == "BUY" and r[3] == "entry: matches the screen" for r in rows)
    status = conn.execute(
        "SELECT DISTINCT status FROM paper_order WHERE user_id=%s", (uid,)
    ).fetchall()
    assert status == [("PENDING",)]  # nothing is filled until the owner approves
    run = conn.execute(
        "SELECT strategy_id, detail FROM paper_run WHERE user_id=%s", (uid,)
    ).fetchone()
    assert run[0] == "screener" and run[1]["universe"]["segments"] == ["large", "mid"]
    assert "decided_month" not in run[1]


def test_holdings_that_still_match_are_left_alone_session_after_session(env):
    conn, ids, uid, lake = env
    for name in ("FAST", "SLOW", "EXTRA"):
        hold(conn, uid, ids[name])
    for day in (JAN, date(2025, 1, 2), date(2025, 1, 3)):
        out = run_day(conn, uid, day=day, now=at(day), lake_root=lake)
        assert out.status == "NO_CHANGE" and "kept its targets" in out.detail["reason"]
    assert conn.execute("SELECT count(*) FROM paper_order WHERE user_id=%s", (uid,)).fetchone() == (
        0,
    )


def test_a_stock_that_starts_matching_is_proposed_even_when_others_are_already_held(env):
    conn, ids, uid, lake = env
    hold(conn, uid, ids["FAST"])
    run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    assert [(r[0], r[1]) for r in orders(conn, uid, JAN)] == [
        (ids["SLOW"], "BUY"),
        (ids["EXTRA"], "BUY"),
    ]


def test_a_held_stock_that_stops_matching_is_proposed_for_sale_that_same_session(env):
    conn, ids, uid, lake = env
    for name in ("FAST", "SLOW", "EXTRA"):
        hold(conn, uid, ids[name])
    before = date(2025, 1, 7)
    assert run_day(conn, uid, day=before, now=at(before), lake_root=lake).status == "NO_CHANGE"
    day = DAYS[CRASH]
    out = run_day(conn, uid, day=day, now=at(day), lake_root=lake)
    assert out.status == "PROPOSED", out.detail
    rows = orders(conn, uid, day)
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (ids["SLOW"], "SELL", D(100))
    ]  # all of it, and nothing else is bought: no other stock matches
    assert rows[0][3].startswith(
        "stop loss: long 100 is 14.93% against its entry"
    )  # it crashed 15% below its cost, so the per-trade stop is what names the sale


def test_it_buys_a_stock_back_on_the_first_session_it_matches_again(env):
    conn, ids, uid, lake = env
    hold(conn, uid, ids["FAST"])
    hold(conn, uid, ids["EXTRA"])  # SLOW was sold after the crash
    quiet = DAYS[CRASH + 20]  # a month's change still reaches back before the crash
    assert run_day(conn, uid, day=quiet, now=at(quiet), lake_root=lake).status == "NO_CHANGE"
    back = DAYS[CRASH + 21]
    out = run_day(conn, uid, day=back, now=at(back), lake_root=lake)
    assert out.status == "PROPOSED"
    assert [(r[0], r[1]) for r in orders(conn, uid, back)] == [(ids["SLOW"], "BUY")]


def test_a_day_with_no_prices_decides_nothing(env):
    conn, _, uid, lake = env
    sat = date(2025, 1, 4)
    out = run_day(conn, uid, day=sat, now=at(sat), lake_root=lake)
    assert out.status == "NO_CHANGE"


def test_an_account_following_a_screener_cannot_be_given_other_settings_by_hand(env):
    conn, _, uid, _ = env
    with pytest.raises(book.PaperError, match="screener"):
        book.update_settings(conn, uid, universe="nifty50")
    assert book.get_account(conn, uid)["universe"] == configs.SEGMENTS


def test_editing_the_strategy_updates_the_account_that_uses_it(env):
    conn, _, uid, _ = env
    cid = configs.list_for(conn, uid)[0]["config_id"]
    wider = {**SCREEN, "segments": ["large", "mid", "small"]}
    configs.update(
        conn, uid, cid, name="Rising", universe=configs.SEGMENTS, max_instruments=None,
        timeframe="1D", params={"max_positions": 10}, screen=wider,
    )  # fmt: skip
    acct = book.get_account(conn, uid)
    assert acct["screen"] == wider and acct["params"] == {"max_positions": 10}


def test_a_screen_on_filed_ratios_proposes_only_stocks_whose_results_were_filed_and_pass(env):
    conn, ids, uid, lake = env
    ends = [
        date(2023, 12, 31),
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
    ]  # all filed before January 2025
    isin = {"FAST": 1, "SLOW": 2, "EXTRA": 3, "FALLING": 4}
    for name, eps in {
        "FAST": 5,
        "EXTRA": 2,
        "FALLING": -3,
    }.items():  # SLOW has no filings; FALLING loses money
        add_filings(conn, ids[name], name, f"INE00000000{isin[name]}", eps, ends, NOW)
    pe = {
        **SCREEN,
        "screen": {
            "conditions": [{"field": "pe", "op": "lt", "value": 1000000}],
            "match": "all",
            "sort": "pe",
            "descending": False,
        },
    }
    cid = configs.create(
        conn, uid, name="Cheap", universe=configs.SEGMENTS, max_instruments=None, timeframe="1D",
        params={"max_positions": 5}, now=NOW, strategy_id="screener", screen=pe,
    )  # fmt: skip
    configs.use(conn, uid, cid)
    out = run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    assert out.status == "PROPOSED", out.detail
    assert sorted(r[0] for r in orders(conn, uid, JAN)) == sorted([ids["FAST"], ids["EXTRA"]])


def test_a_screen_on_the_swing_score_buys_by_score_known_on_the_day_and_not_by_a_later_one(env):
    conn, ids, uid, lake = env
    score_screen = {
        "screen": {
            "conditions": [{"field": "score", "op": "gt", "value": 60}],
            "match": "all",
            "sort": "score",
            "descending": True,
        },
        "segments": ["large", "mid"],
    }
    cid = configs.create(
        conn, uid, name="Scored", universe=configs.SEGMENTS, max_instruments=None, timeframe="1D",
        params={"max_positions": 5}, now=NOW, strategy_id="screener", screen=score_screen,
    )  # fmt: skip
    configs.use(conn, uid, cid)
    for name, s, day in (
        ("FAST", 90, JAN),
        ("EXTRA", 70, JAN),
        ("FALLING", 95, JAN),
        ("SLOW", 50, JAN),
        ("SLOW", 99, date(2025, 1, 6)),
    ):
        conn.execute(
            "INSERT INTO stock_score_history (day, instrument_id, score) VALUES (%s,%s,%s)",
            (day, ids[name], s),
        )
    out = run_day(conn, uid, day=JAN, now=at(JAN), lake_root=lake)
    assert out.status == "PROPOSED", out.detail
    got = {r[0] for r in orders(conn, uid, JAN)}
    assert (
        got == {ids["FAST"], ids["EXTRA"], ids["FALLING"]}
    )  # the faller is bought because its score is high; SLOW's 99 is dated five days later and is not seen

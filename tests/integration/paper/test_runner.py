"""The daily paper runner through the real reader and strategy. ENGINEERING_TEST_ONLY: synthetic prices."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.live.market_calendar import mark_closed
from algo.paper import book
from algo.paper.runner import run_day
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from tests.integration.test_trend_pullback_engine import DAYS, UP, falling, sawtooth
from tests.support.bt import add_action, put_bars
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
PARAMS = {"trend_sma": 200, "entry_rsi": 25, "exit_rsi": 60, "max_positions": 10}
DAY = DAYS[273]  # the last session of a short fall for the first sawtooth name
NOW = datetime.combine(DAY, datetime.min.time(), UTC) + timedelta(hours=13)


@pytest.fixture
def env(conn, tmp_path):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    for k in range(20):
        iid = repo.add_instrument(x, f"S{k:02d}")
        repo.add_alias(iid, "nse", f"S{k:02d}", date(2000, 1, 1))
        put_bars(conn, iid, sawtooth(k) if k < UP else falling())
        ids.append(iid)
    put_list(tmp_path, DAY - timedelta(days=5))
    return conn, ids, tmp_path


def put_list(lake, day, extra=()):
    d = lake / "raw/niftyindices/nifty200_list" / f"dt={day}"
    d.mkdir(parents=True, exist_ok=True)
    rows = "".join(f"S{k:02d} Ltd.,X,S{k:02d},EQ,INE{k:09d}\n" for k in [*range(20), *extra])
    (d / "v1.bin").write_bytes(("Company Name,Industry,Symbol,Series,ISIN Code\n" + rows).encode())


def user(conn, email="jane@example.com", cash="1000000", params=PARAMS, **settings):
    uid = add_user(conn, SimClock(NOW), "TRADER", email)
    book.create_account(
        conn,
        uid,
        strategy_id="trend_pullback",
        params=params,
        initial_cash=D(cash),
        started_on=DAYS[250],
        now=NOW,
        **settings,
    )
    return uid


def orders(conn, uid, status=None):
    sql = "SELECT instrument_id, side, qty, ref_price, reason, status, expires_at, not_before FROM paper_order WHERE user_id=%s"
    sql += " AND status=%s" if status else ""
    args = (uid, status) if status else (uid,)
    return conn.execute(sql + " ORDER BY side DESC, instrument_id", args).fetchall()


def test_oversold_uptrend_names_become_pending_buy_orders_sized_to_their_slot(env):
    conn, ids, lake = env
    uid = user(conn)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "PROPOSED" and out.orders
    rows = orders(conn, uid)
    assert rows and all(
        r[1] == "BUY" and r[5] == "PENDING" and r[4].startswith("entry") for r in rows
    )
    assert {r[0] for r in rows} <= set(ids[:UP])  # the falling names fail the trend test
    for _, _, qty, px, *_ in rows:
        assert qty == (D("0.1") * D(1_000_000) / px).to_integral_value(rounding="ROUND_DOWN")
    assert sum(r[2] * r[3] for r in rows) <= D(1_000_000)
    assert all(r[6] > NOW for r in rows)  # valid until a later session closes
    assert all(NOW < r[7] < r[6] for r in rows)  # and cannot fill before that session opens
    run = conn.execute(
        "SELECT status, strategy_id, strategy_version, detail FROM paper_run WHERE user_id=%s",
        (uid,),
    ).fetchone()
    assert run[:3] == ("PROPOSED", "trend_pullback", "1")
    assert run[3]["label"] == "UNVALIDATED" and run[3]["universe"]["listed"] == 20
    eq = conn.execute(
        "SELECT equity, cash FROM paper_equity WHERE user_id=%s AND day=%s", (uid, DAY)
    )
    assert eq.fetchone() == (D(1_000_000), D(1_000_000))


def test_running_the_same_day_twice_gives_the_same_orders_not_more(env):
    conn, _, lake = env
    uid = user(conn)
    first = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    second = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert second.status == first.status and sorted(second.orders) == sorted(first.orders)
    count = conn.execute("SELECT count(*) FROM paper_order WHERE user_id=%s", (uid,)).fetchone()
    assert count == (len(first.orders),)


def test_a_new_decision_day_retires_the_orders_nobody_answered(env):
    conn, _, lake = env
    uid = user(conn)
    first = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    run_day(conn, uid, day=DAYS[274], now=NOW + timedelta(days=1), lake_root=lake)
    old = conn.execute(
        "SELECT status FROM paper_order WHERE order_id = ANY(%s)", (first.orders,)
    ).fetchall()
    assert old and all(s == ("EXPIRED",) for s in old)


def test_a_holding_that_lost_its_trend_is_proposed_for_sale(env):
    conn, ids, lake = env
    uid = user(conn)
    weak = ids[UP]  # a falling name: below its 200-day average
    book.record_fill(
        conn,
        uid,
        day=DAYS[260],
        side="BUY",
        iid=weak,
        qty=D(100),
        price=D(80),
        commission=D(0),
        charges=[],
        ref="seed",
        now=NOW,
    )
    run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    sells = [r for r in orders(conn, uid) if r[1] == "SELL"]
    assert len(sells) == 1
    assert (sells[0][0], sells[0][2], sells[0][4]) == (weak, D(100), "exit: below_trend")


def test_a_split_on_a_held_name_is_applied_before_the_strategy_decides(env):
    conn, ids, lake = env
    uid = user(conn)
    held = ids[1]
    book.record_fill(
        conn,
        uid,
        day=DAYS[251],
        side="BUY",
        iid=held,
        qty=D(10),
        price=D(150),
        commission=D(0),
        charges=[],
        ref="seed",
        now=NOW,
    )
    add_action(conn, held, DAYS[260], "split", num=D(2), den=D(1))
    run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert book.load(conn, uid).qty(held) == D(20)


def test_cash_limits_what_can_be_bought(env):
    conn, _, lake = env
    uid = user(conn, cash="3000")
    run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert sum(r[2] * r[3] for r in orders(conn, uid)) <= D(3000)


def test_each_user_has_their_own_account_and_orders(env):
    conn, _, lake = env
    a, b = user(conn, "a@example.com", "1000000"), user(conn, "b@example.com", "200000")
    run_day(conn, a, day=DAY, now=NOW, lake_root=lake)
    run_day(conn, b, day=DAY, now=NOW, lake_root=lake)
    qa, qb = orders(conn, a), orders(conn, b)
    assert qa and qb and qa != qb
    assert {r[0] for r in qa} == {r[0] for r in qb}  # the same decision
    assert all(x[2] > y[2] for x, y in zip(qa, qb, strict=True))  # sized to each account


def test_an_account_that_is_off_or_paused_proposes_nothing_and_says_why(env):
    conn, _, lake = env
    off, paused = user(conn, "off@example.com"), user(conn, "p@example.com")
    book.set_enabled(conn, off, False)
    conn.execute(
        "UPDATE paper_account SET attention='rights (ex 2026-11-05) needs review' WHERE user_id=%s",
        (paused,),
    )
    o1 = run_day(conn, off, day=DAY, now=NOW, lake_root=lake)
    o2 = run_day(conn, paused, day=DAY, now=NOW, lake_root=lake)
    assert (o1.status, o2.status) == ("SKIPPED", "SKIPPED")
    assert "switched off" in o1.detail["reason"] and "needs review" in o2.detail["reason"]
    assert orders(conn, off) == [] and orders(conn, paused) == []


def test_data_that_cannot_support_a_decision_is_an_error_not_a_guess(env, tmp_path):
    conn, _, lake = env
    uid = user(conn)
    late = DAYS[-1] + timedelta(days=7)  # no bars exist for this day
    put_list(lake, late - timedelta(days=3))
    out = run_day(conn, uid, day=late, now=NOW + timedelta(days=100), lake_root=lake)
    assert out.status == "ERROR" and "data not ready" in out.detail["reason"]
    assert out.detail["readiness"][0]["code"] == "STALE" and orders(conn, uid) == []
    no_list = run_day(conn, uid, day=DAY, now=NOW, lake_root=tmp_path / "empty")
    assert no_list.status == "ERROR" and "no nifty200_list" in no_list.detail["reason"]


def test_an_account_that_does_not_exist_is_refused(env):
    conn, _, lake = env
    nobody = add_user(conn, SimClock(NOW), "VIEWER", "v@example.com")
    with pytest.raises(book.PaperError, match="no paper account"):
        run_day(conn, nobody, day=DAY, now=NOW, lake_root=lake)


def test_an_unknown_strategy_is_an_error_run(env):
    conn, _, lake = env
    uid = user(conn)
    conn.execute("UPDATE paper_account SET strategy_id='nope' WHERE user_id=%s", (uid,))
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "ERROR" and "nope" in out.detail["reason"]


def extra_member(conn, lake, bars=None):
    """A 21st member of the Nifty 200 list: one stock in 21 is below the 5% tolerance for unready names."""
    repo = InstrumentRepo(conn)
    iid = repo.add_instrument(repo.add_exchange("XBSE", "IN", "Asia/Kolkata", "INR", "BSE"), "S20")
    repo.add_alias(iid, "nse", "S20", date(2000, 1, 1))
    if bars is not None:
        put_bars(conn, iid, bars)
    put_list(lake, DAY - timedelta(days=5), extra=[20])
    return iid


def test_a_member_with_no_bars_at_all_or_only_later_ones_is_simply_not_ready(env):
    conn, _, lake = env
    extra_member(conn, lake)
    uid = user(conn)
    assert run_day(conn, uid, day=DAY, now=NOW, lake_root=lake).status == "PROPOSED"


def test_a_member_that_only_starts_trading_after_the_decision_day_is_not_ready_either(env):
    conn, _, lake = env
    extra_member(conn, lake, {d: D(100) for d in DAYS[300:]})
    uid = user(conn)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "PROPOSED" and out.detail["audit"]["not_ready"]


def test_a_held_position_that_cannot_be_traded_today_limits_what_can_be_bought(env):
    conn, _, lake = env
    stale = extra_member(conn, lake, {d: D(200) for d in DAYS[:200]})  # no bar on the decision day
    uid = user(conn, cash="700000")
    book.record_fill(
        conn,
        uid,
        day=DAYS[250],
        side="BUY",
        iid=stale,
        qty=D(3000),
        price=D(200),
        commission=D(0),
        charges=[],
        ref="seed",
        now=NOW,
    )
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    rows = orders(conn, uid)
    assert all(
        r[0] != stale for r in rows
    )  # it is neither sold nor topped up: there is no price today
    assert sum(r[2] * r[3] for r in rows) <= D(
        100_000
    )  # only the cash left after the 600,000 position
    assert out.detail["skipped_for_cash"]


def test_a_lot_size_bigger_than_the_slot_means_nothing_to_buy(env):
    conn, ids, lake = env
    repo = InstrumentRepo(conn)
    for iid in ids:
        repo.add_terms(iid, date(2000, 1, 1), None, D(1), D("0.05"), D(1_000_000))
    uid = user(conn)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert (
        out.status == "NO_CHANGE"
        and "already match" in out.detail["reason"]
        and orders(conn, uid) == []
    )


def test_with_no_session_in_the_next_week_orders_stay_open_four_days(env):
    conn, _, lake = env
    for k in range(1, 8):
        mark_closed(
            conn, day=DAY + timedelta(days=k), note="closed", source="manual", actor=None, now=NOW
        )
    uid = user(conn)
    run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert {(r[7], r[6]) for r in orders(conn, uid)} == {(NOW, NOW + timedelta(days=4))}


def test_a_strategy_that_keeps_its_targets_proposes_nothing(env, monkeypatch):
    conn, _, lake = env

    class Keeps(TrendPullback):
        def on_schedule(self, ctx):
            return None

    from algo.paper import runner

    monkeypatch.setitem(runner.STRATEGIES, "trend_pullback", (Keeps, TrendPullbackParams))
    uid = user(conn)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "NO_CHANGE" and "kept its targets" in out.detail["reason"]


def test_an_error_run_can_be_retried_once_the_cause_is_fixed(env, tmp_path):
    conn, _, lake = env
    uid = user(conn)
    empty = tmp_path / "empty"
    assert run_day(conn, uid, day=DAY, now=NOW, lake_root=empty).status == "ERROR"
    assert run_day(conn, uid, day=DAY, now=NOW, lake_root=lake).status == "PROPOSED"
    assert conn.execute("SELECT count(*) FROM paper_run WHERE user_id=%s", (uid,)).fetchone() == (
        1,
    )


def test_the_account_chooses_which_index_the_strategy_trades(env):
    conn, ids, lake = env
    d = lake / "raw/niftyindices/nifty50_list" / f"dt={DAY - timedelta(days=5)}"
    d.mkdir(parents=True)
    rows = "".join(f"S{k:02d} Ltd.,X,S{k:02d},EQ,INE{k:09d}\n" for k in range(5))
    (d / "v1.bin").write_bytes(("Company Name,Industry,Symbol,Series,ISIN Code\n" + rows).encode())
    uid = user(conn, universe="nifty50")
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.detail["universe"]["universe"] == "nifty50" and out.detail["audit"]["members"] == 5
    assert {r[0] for r in orders(conn, uid)} <= set(ids[:5])


def test_the_instrument_cap_keeps_the_most_liquid_names(env):
    conn, ids, lake = env
    conn.execute(
        "UPDATE bar_1d SET volume = 1 WHERE instrument_id = ANY(%s)", (ids[5:],)
    )  # all but five are illiquid
    uid = user(conn, max_instruments=5)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.detail["universe"]["capped_to"] == 5 and out.detail["audit"]["members"] == 5
    assert out.orders and {r[0] for r in orders(conn, uid)} <= set(ids[:5])
    roomy = user(
        conn, "big@example.com", max_instruments=500
    )  # a cap above the universe size changes nothing
    assert (
        "capped_to" not in run_day(conn, roomy, day=DAY, now=NOW, lake_root=lake).detail["universe"]
    )


def test_the_strategy_is_never_called_when_the_data_is_not_ready_and_the_run_recovers(
    env, monkeypatch
):
    conn, ids, lake = env
    uid = user(conn)
    calls = []
    real = TrendPullback.on_schedule
    monkeypatch.setattr(
        TrendPullback, "on_schedule", lambda self, ctx: calls.append(1) or real(self, ctx)
    )
    conn.execute(  # NSE refused one of the files in the last month
        "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,at)"
        " VALUES ('nse','bhav',%s,1,'x','quarantined',%s)",
        (DAY - timedelta(days=3), NOW),
    )
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "ERROR" and "QUARANTINED" in out.detail["reason"]
    assert [r["code"] for r in out.detail["readiness"]] == ["QUARANTINED"]
    assert calls == [] and orders(conn, uid) == []
    conn.execute("DELETE FROM partition_load")  # a person recovered the file
    assert run_day(conn, uid, day=DAY, now=NOW, lake_root=lake).status == "PROPOSED"
    assert calls == [1]


def test_a_weekday_without_bars_blocks_the_decision_too(env):
    conn, ids, lake = env
    uid = user(conn)
    gone = DAY - timedelta(days=7)
    assert gone.weekday() < 5
    conn.execute("DELETE FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date=%s", (gone,))
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert out.status == "ERROR" and [r["code"] for r in out.detail["readiness"]] == ["MISSING_DAY"]


def test_a_paused_strategy_or_a_global_pause_means_the_runner_proposes_nothing_and_says_why(env):
    from algo.risk import store

    conn, ids, lake = env
    uid = user(conn)
    store.change(conn, "pause", "trend_pullback", by="jane", reason="looking", now=NOW)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=lake)
    assert (
        out.status == "SKIPPED"
        and out.detail["reason"] == "the kill switch is PAUSE"
        and orders(conn, uid) == []
    )
    store.change(conn, "resume", "trend_pullback", by="jane", reason="ok", now=NOW)
    store.change(conn, "cancel", None, by="joe", reason="data", now=NOW)
    assert (
        run_day(conn, uid, day=DAY, now=NOW, lake_root=lake).detail["reason"]
        == "the kill switch is CANCEL"
    )
    store.change(conn, "resume", None, by="joe", reason="fixed", now=NOW)
    assert (
        run_day(conn, uid, day=DAY, now=NOW, lake_root=lake).status == "PROPOSED"
    )  # a skipped run is retried

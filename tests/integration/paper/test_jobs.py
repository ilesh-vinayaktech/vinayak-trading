"""The scheduled paper cycle: decide for every enabled account after the evening data jobs, fill and expire approved orders through the day."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, jobs, orders
from algo.risk import store as kill_switch
from tests.integration.paper import test_runner as tr
from tests.support.bt import put_bars

pytestmark = pytest.mark.integration
env = tr.env  # the runner tests' fixture: 20 instruments, a Nifty 200 list and a year of bars
DAY, NOW, user, list_orders = tr.DAY, tr.NOW, tr.user, tr.orders


def statuses(results):
    return sorted(r.status for _, r in results)


def test_every_enabled_account_gets_its_decision_and_a_switched_off_one_does_not(env):
    conn, ids, lake = env
    jane, bob, off = (
        user(conn, "jane@example.com"),
        user(conn, "bob@example.com"),
        user(conn, "off@example.com"),
    )
    book.set_enabled(conn, off, False)
    results = jobs.run_accounts(conn, NOW, lake_root=lake, day=DAY)
    assert {u for u, _ in results} == {jane, bob} and statuses(results) == ["PROPOSED", "PROPOSED"]
    assert list_orders(conn, jane) and list_orders(conn, bob) and list_orders(conn, off) == []
    again = jobs.run_accounts(
        conn, NOW, lake_root=lake, day=DAY
    )  # a rerun the same evening proposes nothing new
    assert statuses(again) == ["PROPOSED", "PROPOSED"] and len(list_orders(conn, jane)) == len(
        results[0][1].orders
    )


def test_an_account_that_cannot_decide_is_reported_and_does_not_stop_the_others(env):
    conn, ids, lake = env
    paused, fine = user(conn, "paused@example.com"), user(conn, "fine@example.com")
    kill_switch.change(conn, "pause", "trend_pullback", by="jane", reason="looking", now=NOW)
    results = dict(jobs.run_accounts(conn, NOW, lake_root=lake, day=DAY))
    assert {r.status for r in results.values()} == {
        "SKIPPED"
    }  # both are the same strategy, both paused
    assert paused in results and fine in results
    kill_switch.change(conn, "resume", "trend_pullback", by="jane", reason="ok", now=NOW)
    (bad,) = [r for _, r in jobs.run_accounts(conn, NOW, lake_root=lake / "nowhere", day=DAY)][:1]
    assert bad.status == "ERROR" and "nifty200_list" in bad.detail["reason"]


def test_the_decision_day_is_the_newest_session_once_its_file_should_be_published(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    fri, mon = date(2026, 11, 13), date(2026, 11, 16)
    put_bars(conn, iid, {date(2026, 11, 12): D(10), fri: D(11)})
    after = datetime(2026, 11, 13, 13, 30, tzinfo=UTC)  # 19:00 IST on the Friday
    assert jobs.decision_day(conn, after) == fri
    assert (
        jobs.decision_day(conn, datetime(2026, 11, 15, 8, 0, tzinfo=UTC)) == fri
    )  # a Sunday: Friday is still the latest session
    monday_evening = datetime(2026, 11, 16, 13, 30, tzinfo=UTC)
    assert (
        jobs.decision_day(conn, monday_evening) is None
    )  # Monday's file is expected and not here: nothing to decide on
    put_bars(conn, iid, {mon: D(12)})
    assert jobs.decision_day(conn, monday_evening) == mon


def test_no_bars_at_all_means_no_decision_day(conn):
    migrate(conn)
    assert jobs.decision_day(conn, NOW) is None


def test_the_order_tick_fills_approved_orders_at_the_next_live_open_and_expires_the_rest(env):
    from pathlib import Path

    from algo.backtest.costs.schedule_store import import_files

    conn, ids, lake = env
    import_files(conn, Path(__file__).resolve().parents[2] / "fixtures/cost_schedules", now=NOW)
    uid = user(conn)
    iid = ids[0]
    open_ = datetime(2026, 11, 17, 3, 45, tzinfo=UTC)
    close = open_ + timedelta(hours=6, minutes=15)
    evening = open_ - timedelta(hours=8)
    for qty in (10, 20):
        oid = conn.execute(
            "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
            " VALUES (%s,%s,%s,'BUY',%s,100,'entry',%s,%s,%s) RETURNING order_id",
            (uid, date(2026, 11, 16), iid, qty, evening, open_, close),
        ).fetchone()[0]
        orders.approve(conn, oid, user_id=uid, now=evening)
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at)"
        " VALUES (%s,%s,100,100,100,100,1000,5,false,%s)",
        (iid, open_ + timedelta(minutes=1), open_ + timedelta(minutes=1)),
    )
    first = jobs.process_orders(conn, open_ + timedelta(minutes=5))
    assert (first.filled, first.failed, first.waiting) == (2, 0, 0)
    assert conn.execute("SELECT count(*) FROM paper_order WHERE status='FILLED'").fetchone() == (2,)
    assert all(
        p > D(100) for (p,) in conn.execute("SELECT fill_price FROM paper_order")
    )  # slippage worked against us
    later = jobs.process_orders(conn, close + timedelta(minutes=1))
    assert (later.filled, later.failed, later.waiting) == (0, 0, 0)


def test_the_cost_policy_is_the_verified_schedule_book_for_the_broker_with_the_studies_default_slippage(
    conn,
):
    migrate(conn)
    policy = jobs.cost_policy(conn)
    assert policy.name == "zerodha-delivery" and jobs.SLIPPAGE_BPS == D(5)

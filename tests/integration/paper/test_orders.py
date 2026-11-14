from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, orders
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)  # 10 bps commission
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)  # Friday 09:15 IST
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)  # Thursday ~19:45 IST, after the decision


def minute(n):
    return OPEN + timedelta(minutes=n)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    jane = add_user(conn, SimClock(EVENING), "TRADER", "jane@example.com")
    bob = add_user(conn, SimClock(EVENING), "TRADER", "bob@example.com")
    for u in (jane, bob):
        book.create_account(
            conn,
            u,
            strategy_id="trend_pullback",
            params={},
            initial_cash=D(100_000),
            started_on=date(2026, 11, 2),
            now=EVENING,
        )
    return conn, jane, bob, iid


def propose(conn, user, iid, side="BUY", qty=100, ref=D(200)):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,'entry',%s,%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, side, qty, ref, EVENING, OPEN, CLOSE),
    ).fetchone()[0]


def live_bar(conn, iid, n, price):
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at) VALUES (%s,%s,%s,%s,%s,%s,1000,5,false,%s)",
        (iid, minute(n), price, price, price, price, minute(n)),
    )


def status(conn, oid):
    return conn.execute(
        "SELECT status, failure FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone()


def fill(conn, now, slippage=0):
    return orders.fill_due(conn, now, cost=COST, slippage_bps=D(slippage))


def test_an_owner_approves_or_rejects_their_own_pending_order_and_nobody_elses(env):
    conn, jane, bob, iid = env
    a, b, c = propose(conn, jane, iid), propose(conn, jane, iid), propose(conn, bob, iid)
    orders.approve(conn, a, user_id=jane, now=EVENING)
    orders.reject(conn, b, user_id=jane, now=EVENING)
    assert status(conn, a) == ("APPROVED", None) and status(conn, b) == ("REJECTED", None)
    row = conn.execute("SELECT decided_by, decided_at FROM paper_order WHERE order_id=%s", (a,))
    assert row.fetchone() == (jane, EVENING)
    with pytest.raises(orders.OrderError, match="no such order"):
        orders.approve(conn, c, user_id=jane, now=EVENING)  # bob's order
    with pytest.raises(orders.OrderError, match="no such order"):
        orders.reject(conn, c, user_id=jane, now=EVENING)
    assert status(conn, c) == ("PENDING", None)


def test_an_order_can_only_be_answered_once_and_not_after_it_expired_or_while_paused(env):
    conn, jane, _, iid = env
    a = propose(conn, jane, iid)
    orders.approve(conn, a, user_id=jane, now=EVENING)
    for act in (orders.approve, orders.reject):
        with pytest.raises(orders.OrderError, match="already approved"):
            act(conn, a, user_id=jane, now=EVENING)
    late = propose(conn, jane, iid)
    with pytest.raises(orders.OrderError, match="expired"):
        orders.approve(conn, late, user_id=jane, now=CLOSE + timedelta(minutes=1))
    assert status(conn, late)[0] == "EXPIRED"
    paused = propose(conn, jane, iid)
    conn.execute(
        "UPDATE paper_account SET attention='rights needs review' WHERE user_id=%s", (jane,)
    )
    with pytest.raises(orders.OrderError, match="paused"):
        orders.approve(conn, paused, user_id=jane, now=EVENING)
    conn.execute("UPDATE paper_account SET attention=NULL, enabled=false WHERE user_id=%s", (jane,))
    with pytest.raises(orders.OrderError, match="paused"):
        orders.approve(conn, paused, user_id=jane, now=EVENING)
    assert status(conn, paused)[0] == "PENDING"


def test_an_approved_order_waits_for_a_live_price_then_fills_at_the_sessions_first_open_with_costs(
    env,
):
    conn, jane, _, iid = env
    oid = propose(conn, jane, iid, qty=100)
    orders.approve(conn, oid, user_id=jane, now=EVENING)
    assert fill(conn, EVENING) == orders.FillReport(0, 0, 1)  # no price yet
    live_bar(conn, iid, 0, D(201))
    live_bar(conn, iid, 1, D(205))
    assert fill(conn, minute(2), 10) == orders.FillReport(1, 0, 0)
    row = conn.execute(
        "SELECT status, fill_day, fill_price, fill_commission, filled_at FROM paper_order WHERE order_id=%s",
        (oid,),
    ).fetchone()
    assert row == (
        "FILLED",
        date(2026, 11, 13),
        D("201.201"),
        D("20.1201"),
        minute(2),
    )  # 10 bps worse than the open
    ledger = book.load(conn, jane)
    assert ledger.qty(iid) == D(100) and ledger.cash == D(100_000) - D("20120.1") - D("20.1201")
    assert fill(conn, minute(3), 10) == orders.FillReport(0, 0, 0)  # nothing twice


def test_approving_during_the_session_fills_at_the_next_minutes_open_never_at_a_price_already_gone(
    env,
):
    conn, jane, _, iid = env
    for n, p in ((0, 200), (1, 210), (2, 220), (3, 230)):
        live_bar(conn, iid, n, D(p))
    oid = propose(conn, jane, iid, qty=10)
    orders.approve(conn, oid, user_id=jane, now=minute(1) + timedelta(seconds=20))  # 09:16:20
    fill(conn, minute(5))
    price = conn.execute("SELECT fill_price FROM paper_order WHERE order_id=%s", (oid,)).fetchone()
    assert price == (D(220),)  # the 09:17 bar


def test_a_sale_is_filled_lower_and_one_that_cannot_happen_fails_with_the_reason(env):
    conn, jane, bob, iid = env
    book.record_fill(
        conn,
        jane,
        day=date(2026, 11, 3),
        side="BUY",
        iid=iid,
        qty=D(50),
        price=D(100),
        commission=D(0),
        charges=[],
        ref="seed",
        now=EVENING,
    )
    live_bar(conn, iid, 0, D(200))
    sell, short = propose(conn, jane, iid, "SELL", 50), propose(conn, bob, iid, "SELL", 5)
    big = propose(conn, jane, iid, "BUY", 100_000)
    with pytest.raises(orders.OrderError, match="REDUCE_ONLY_VIOLATION"):
        orders.approve(
            conn, short, user_id=bob, now=EVENING
        )  # selling what you do not hold is now refused at approval
    conn.execute(  # forced past the approval: the book still refuses it at the fill
        "UPDATE paper_order SET status='APPROVED', decided_at=%s WHERE order_id=%s",
        (EVENING, short),
    )
    for oid, who in ((sell, jane), (big, jane)):
        orders.approve(conn, oid, user_id=who, now=EVENING)
    assert fill(conn, minute(1), 100) == orders.FillReport(1, 2, 0)
    price = conn.execute("SELECT fill_price FROM paper_order WHERE order_id=%s", (sell,)).fetchone()
    assert price == (D(198),)  # 1% under the open
    assert "do not hold" in status(conn, short)[1] and "not enough cash" in status(conn, big)[1]
    assert status(conn, short)[0] == status(conn, big)[0] == "FAILED"


def test_a_paused_account_is_not_filled_until_it_is_released(env):
    conn, jane, _, iid = env
    live_bar(conn, iid, 0, D(200))
    oid = propose(conn, jane, iid)
    orders.approve(conn, oid, user_id=jane, now=EVENING)
    conn.execute("UPDATE paper_account SET enabled=false WHERE user_id=%s", (jane,))
    assert fill(conn, minute(1)) == orders.FillReport(0, 0, 1)
    conn.execute("UPDATE paper_account SET enabled=true WHERE user_id=%s", (jane,))
    assert fill(conn, minute(2)) == orders.FillReport(1, 0, 0)


def test_unanswered_orders_expire_and_approved_ones_that_never_found_a_price_fail(env):
    conn, jane, _, iid = env
    unanswered, approved = propose(conn, jane, iid), propose(conn, jane, iid)
    fine = propose(conn, jane, iid)
    orders.approve(conn, approved, user_id=jane, now=EVENING)
    assert orders.expire_due(conn, CLOSE - timedelta(minutes=1)) == (0, 0)
    assert orders.expire_due(conn, CLOSE) == (2, 1)
    assert status(conn, unanswered)[0] == status(conn, fine)[0] == "EXPIRED"
    assert status(conn, approved) == ("FAILED", "not filled before the order expired")
    assert orders.expire_due(conn, CLOSE) == (0, 0)


def test_the_list_shows_a_users_own_orders_and_can_filter_by_status(env):
    conn, jane, bob, iid = env
    first = propose(conn, jane, iid)
    second = propose(conn, jane, iid, "SELL", 5)
    propose(conn, bob, iid)
    orders.reject(conn, first, user_id=jane, now=EVENING)
    rows = orders.list_orders(conn, jane)
    assert {r["order_id"] for r in rows} == {first, second} and all(
        r["symbol"] == "AAA" for r in rows
    )
    assert [r["order_id"] for r in orders.list_orders(conn, jane, statuses=["PENDING"])] == [second]
    assert orders.get_order(conn, first, user_id=jane)["status"] == "REJECTED"
    assert orders.get_order(conn, first, user_id=bob) is None

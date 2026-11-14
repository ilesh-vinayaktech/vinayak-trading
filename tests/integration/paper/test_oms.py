"""The paper path runs on the OMS: approving sends the order through the OMS to a PaperBroker, fills and cancellations come back as broker
updates, and the OMS order log (oms_event) is the persistent record that reconciles against the paper orders."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.execution.orders import State, client_order_id, replay
from algo.paper import book, orders
from algo.paper import oms as paper_oms
from algo.risk import store as kill_switch
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)
LATER = OPEN + timedelta(minutes=5)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    jane = add_user(conn, SimClock(EVENING), "TRADER", "jane@example.com")
    book.create_account(
        conn,
        jane,
        strategy_id="trend_pullback",
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    return conn, jane, iid


def propose(conn, user, iid, side="BUY", qty=100, ref=D(200)):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,'entry',%s,%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, side, qty, ref, EVENING, OPEN, CLOSE),
    ).fetchone()[0]


def live_bar(conn, iid, n, price):
    t = OPEN + timedelta(minutes=n)
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at) VALUES (%s,%s,%s,%s,%s,%s,1000,5,false,%s)",
        (iid, t, price, price, price, price, t),
    )


def fill(conn, now=LATER, slippage=0):
    return orders.fill_due(conn, now, cost=COST, slippage_bps=D(slippage))


def cid(oid, strategy="trend_pullback"):
    return client_order_id(strategy, str(oid))


def omsorder(conn, oid):
    return paper_oms.build(conn, EVENING).orders[cid(oid)]  # a fresh OMS, as after a restart


def test_approving_sends_the_order_through_the_oms_and_the_paper_broker_and_it_survives_a_restart(
    env,
):
    conn, jane, iid = env
    oid = propose(conn, jane, iid)
    orders.approve(conn, oid, user_id=jane, now=EVENING)
    o = omsorder(conn, oid)
    assert (o.state, o.qty, o.instrument_id, o.broker_order_id) == (
        State.SUBMITTED,
        100,
        iid,
        str(oid),
    )
    assert conn.execute(
        "SELECT status, decided_by FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone() == ("APPROVED", jane)
    events = paper_oms.build(conn, EVENING).events[cid(oid)]
    assert [e.state for e in events] == [None, State.SUBMITTING, State.SUBMITTED] and replay(
        events
    ) == o


def test_a_breached_order_never_reaches_the_oms_or_the_broker(env):
    conn, jane, iid = env
    from algo.paper import risk

    risk.set_limits(conn, jane, {"max_order_value": 100})
    oid = propose(conn, jane, iid)
    with pytest.raises(orders.OrderError, match="risk: MAX_VALUE"):
        orders.approve(conn, oid, user_id=jane, now=EVENING)
    assert paper_oms.build(conn, EVENING).orders == {}
    assert conn.execute("SELECT status FROM paper_order WHERE order_id=%s", (oid,)).fetchone() == (
        "PENDING",
    )


def test_a_fill_comes_back_as_a_broker_update_with_the_filled_quantity_and_price(env):
    conn, jane, iid = env
    oid = propose(conn, jane, iid, qty=40)
    orders.approve(conn, oid, user_id=jane, now=EVENING)
    live_bar(conn, iid, 0, 200)
    assert fill(conn, slippage=100).filled == 1
    price = conn.execute("SELECT fill_price FROM paper_order WHERE order_id=%s", (oid,)).fetchone()[
        0
    ]
    o = omsorder(conn, oid)
    assert (o.state, o.filled_qty, o.avg_price) == (State.FILLED, 40, price) and price == D(
        202
    )  # 1% over the open
    fill(conn)  # nothing new: the OMS is not touched twice
    assert len(paper_oms.build(conn, EVENING).events[cid(oid)]) == 4


def test_a_refused_fill_is_a_rejected_order_with_the_books_reason(env):
    conn, jane, iid = env
    oid = propose(conn, jane, iid, qty=100_000)  # more than the account can pay for
    orders.approve(conn, oid, user_id=jane, now=EVENING)
    live_bar(conn, iid, 0, 200)
    assert fill(conn).failed == 1
    o = omsorder(conn, oid)
    assert o.state is State.REJECTED and "not enough cash" in o.reason


def test_the_kill_switch_cancel_and_an_expiry_both_end_the_oms_order(env):
    conn, jane, iid = env
    cancelled, expired = propose(conn, jane, iid, qty=10), propose(conn, jane, iid, qty=10)
    orders.approve(conn, cancelled, user_id=jane, now=EVENING)
    kill_switch.change(conn, "cancel", None, by="jane", reason="data problem", now=EVENING)
    fill(conn)
    o = omsorder(conn, cancelled)
    assert o.state is State.CANCELLED and "data problem" in o.reason
    kill_switch.change(conn, "resume", None, by="jane", reason="ok", now=EVENING)
    orders.approve(conn, expired, user_id=jane, now=EVENING)
    assert orders.expire_due(conn, CLOSE + timedelta(minutes=1)) == (0, 1)
    assert omsorder(conn, expired).state is State.EXPIRED


def test_the_oms_and_the_paper_orders_reconcile_and_a_difference_is_found(env):
    conn, jane, iid = env
    a, b = propose(conn, jane, iid, qty=10), propose(conn, jane, iid, qty=10)
    orders.approve(conn, a, user_id=jane, now=EVENING)
    orders.approve(conn, b, user_id=jane, now=EVENING)
    live_bar(conn, iid, 0, 200)
    fill(conn)
    assert paper_oms.reconcile(conn, LATER) == []
    conn.execute(
        "UPDATE paper_order SET status='APPROVED' WHERE order_id=%s", (a,)
    )  # the order table disagrees with the OMS log
    assert [m.kind for m in paper_oms.reconcile(conn, LATER)] == ["STATE_MISMATCH"]


def test_orders_approved_before_the_oms_existed_are_adopted_once_not_duplicated(env):
    conn, jane, iid = env
    old = propose(conn, jane, iid, qty=10)
    conn.execute(
        "UPDATE paper_order SET status='APPROVED', decided_at=%s, decided_by=%s WHERE order_id=%s",
        (EVENING, jane, old),
    )
    assert paper_oms.build(conn, EVENING).orders == {}  # the OMS has never seen it
    paper_oms.sync(conn, EVENING)
    paper_oms.sync(conn, EVENING)
    o = omsorder(conn, old)
    assert (
        o.state is State.ACKED and len(paper_oms.build(conn, EVENING).events[cid(old)]) == 4
    )  # NEW, SUBMITTING, SUBMITTED, OPEN
    live_bar(conn, iid, 0, 200)
    fill(conn)
    assert omsorder(conn, old).state is State.FILLED
    assert paper_oms.reconcile(conn, LATER) == []


def test_owner_rejected_and_unanswered_orders_are_not_orders_at_the_broker(env):
    conn, jane, iid = env
    rejected, unanswered = propose(conn, jane, iid), propose(conn, jane, iid)
    orders.reject(conn, rejected, user_id=jane, now=EVENING)
    paper_oms.sync(conn, EVENING)
    oms = paper_oms.build(conn, EVENING)
    assert oms.orders == {} and paper_oms.PaperBroker(conn, EVENING).orders() == [] and unanswered


def test_the_broker_refuses_an_order_that_is_not_pending_and_cancels_only_open_ones(env):
    from algo.execution.broker import BrokerError, BrokerRejected

    conn, jane, iid = env
    oid = propose(conn, jane, iid)
    broker = paper_oms.PaperBroker(conn, EVENING)
    with pytest.raises(BrokerRejected, match="not pending"):
        broker.place_order(None, "UNKNOWNTAG")  # nobody expected this tag
    orders.reject(conn, oid, user_id=jane, now=EVENING)
    broker.expect(cid(oid), oid, jane)
    with pytest.raises(BrokerRejected, match="not pending"):
        broker.place_order(None, cid(oid))  # already answered
    with pytest.raises(BrokerError, match="not open"):
        broker.cancel_order(str(oid))

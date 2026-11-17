# ruff: noqa: E501
"""One pipeline, step 2: what the broker really filled is booked into the SAME event book paper fills go to (so cash, positions and P&L come from the same
Ledger), with the same cost policy. Partial fills book as increments, once each; a real fill is a fact and is booked even when it overspends the estimate."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.execution.event_store import DbStore
from algo.execution.kite_account import Account
from algo.execution.oms import Oms
from algo.execution.orders import client_order_id
from algo.live.process import LiveProcess
from algo.paper import book, orders
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.limits import Limits
from tests.support.fake_broker import FakeBroker
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)  # 10 bps commission
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)  # Friday 09:15 IST
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)
STRATEGY = "trend_pullback"


class Reader:
    def read(self):
        return Account(D(0), [], [])


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    repo.add_terms(iid, date(2000, 1, 1), None, D(1), D("0.05"), D(1))
    clock = SimClock(OPEN)
    user = add_user(conn, SimClock(EVENING), "TRADER", "live@example.com")
    book.create_account(
        conn,
        user,
        strategy_id=STRATEGY,
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    conn.execute("UPDATE paper_account SET mode='LIVE' WHERE user_id=%s", (user,))
    broker = FakeBroker()
    oms = Oms(
        broker,
        RiskEngine(Limits(), risk_store.load(conn)),
        clock,
        store=DbStore(conn),
        own_positions_only=True,
    )
    proc = LiveProcess(oms, Reader(), {}, clock, conn, host="h", pid=1, cost=COST)
    proc.start()
    return conn, user, iid, clock, broker, proc


def send(conn, proc, user, iid, qty=10, side="BUY"):
    oid = conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,200,'entry',%s,%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, side, qty, EVENING, OPEN, CLOSE),
    ).fetchone()[0]
    orders.approve(conn, oid, user_id=user, now=OPEN)
    proc.tick()
    return oid, client_order_id(STRATEGY, str(oid))


def row(conn, oid):
    return conn.execute(
        "SELECT status, fill_price, failure FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone()


def events(conn, user):
    return conn.execute(
        "SELECT kind, qty, price, commission, ref FROM paper_event WHERE user_id=%s ORDER BY event_id",
        (user,),
    ).fetchall()


def test_a_full_fill_is_booked_once_with_charges_and_moves_cash_and_position(env):
    conn, user, iid, clock, broker, proc = env
    oid, tag = send(conn, proc, user, iid)
    broker.move(tag, "COMPLETE", filled_qty=10, avg_price=D(200))
    proc.tick()
    proc.tick()  # nothing new: nothing booked again
    assert len(events(conn, user)) == 1
    kind, qty, price, commission, _ = events(conn, user)[0]
    assert (kind, qty, price, commission) == ("BUY", D(10), D(200), D("2.0000"))
    assert row(conn, oid)[:2] == ("FILLED", D(200))
    ledger = book.load(conn, user)
    assert ledger.qty(iid) == D(10) and ledger.cash == D(100_000) - D(2000) - D("2.0000")
    assert ledger.reconcile() == []


def test_partial_fills_book_as_increments_that_add_up_to_the_broker_totals(env):
    conn, user, iid, clock, broker, proc = env
    oid, tag = send(conn, proc, user, iid)
    broker.move(tag, "PARTIAL", filled_qty=4, avg_price=D(200))
    proc.tick()
    assert row(conn, oid)[0] == "APPROVED"  # still working
    broker.move(
        tag, "COMPLETE", filled_qty=10, avg_price=D(203)
    )  # the other 6 came at 205: (10*203 - 4*200) / 6
    proc.tick()
    proc.tick()
    got = [(e[1], e[2]) for e in events(conn, user)]
    assert got == [(D(4), D(200)), (D(6), D(205))]
    assert row(conn, oid)[0] == "FILLED"
    assert book.load(conn, user).qty(iid) == D(10)


def test_an_order_cancelled_after_a_partial_fill_keeps_what_filled_and_says_so(env):
    conn, user, iid, clock, broker, proc = env
    oid, tag = send(conn, proc, user, iid)
    broker.move(tag, "PARTIAL", filled_qty=4, avg_price=D(200))
    proc.tick()
    broker.move(tag, "CANCELLED", filled_qty=4, avg_price=D(200))
    proc.tick()
    assert book.load(conn, user).qty(iid) == D(4)  # the 4 shares are really held
    status, _, why = row(conn, oid)
    assert status == "FAILED" and "4 of 10" in why


def test_an_order_the_broker_refused_fails_with_nothing_booked(env):
    conn, user, iid, clock, broker, proc = env
    oid, tag = send(conn, proc, user, iid)
    broker.move(tag, "REJECTED")
    proc.tick()
    assert events(conn, user) == [] and row(conn, oid)[0] == "FAILED"


def test_a_real_fill_is_booked_even_when_it_costs_more_than_the_book_thought_it_had(env):
    conn, user, iid, clock, broker, proc = env
    oid, tag = send(conn, proc, user, iid, qty=10)
    broker.move(
        tag, "COMPLETE", filled_qty=10, avg_price=D(20_000)
    )  # a price the estimate never saw
    proc.tick()
    assert len(events(conn, user)) == 1  # the shares are held whatever the estimate said
    assert book.load(conn, user).cash < 0


def test_a_paper_account_book_is_not_touched(env):
    conn, user, iid, clock, broker, proc = env
    other = add_user(conn, SimClock(EVENING), "TRADER", "paper@example.com")
    book.create_account(
        conn,
        other,
        strategy_id=STRATEGY,
        params={},
        initial_cash=D(5_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    oid, tag = send(conn, proc, user, iid)
    broker.move(tag, "COMPLETE", filled_qty=10, avg_price=D(200))
    proc.tick()
    assert events(conn, other) == []

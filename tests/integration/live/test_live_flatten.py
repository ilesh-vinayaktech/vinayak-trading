# ruff: noqa: E501
"""FLATTEN for a live account, on the one shared pipeline: the closing order is made the same way paper makes it (from the account's OWN book, so shares the
owner holds by hand are never in it), approved by the operator's FLATTEN itself, and sent by the live process; the process cancels what else was open but never
the closing order, and sends it once however often flatten runs."""

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
from algo.paper import oms as paper_oms
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.limits import Limits
from tests.support.bt import put_bars
from tests.support.fake_broker import FakeBroker
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)
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
    put_bars(conn, iid, {date(2026, 11, 12): D(200)})
    clock = SimClock(OPEN)
    owner = add_user(conn, SimClock(EVENING), "TRADER", "live@example.com")
    book.create_account(
        conn,
        owner,
        strategy_id=STRATEGY,
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
        mode="LIVE",
    )
    key = book.account_key(owner, "LIVE")
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
    return conn, owner, key, iid, clock, broker, proc


def buy(conn, proc, key, iid, qty, decision_day=date(2026, 11, 12)):
    oid = conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,'BUY',%s,200,'entry',%s,%s,%s) RETURNING order_id",
        (key, decision_day, iid, qty, EVENING, OPEN, CLOSE),
    ).fetchone()[0]
    orders.approve(conn, oid, user_id=key, now=OPEN)
    proc.tick()
    return oid, client_order_id(STRATEGY, str(oid))


def hold(conn, proc, broker, key, iid, qty=10):
    """The platform really bought `qty`: sent, filled by the broker, booked."""
    _, tag = buy(conn, proc, key, iid, qty)
    broker.move(tag, "COMPLETE", filled_qty=qty, avg_price=D(200))
    proc.tick()
    assert book.load(conn, key).qty(iid) == qty


def flatten_switch(conn):
    risk_store.change(
        conn, "flatten", None, by="o", reason="drill", now=OPEN, emergency_override=True
    )


def closing(conn, key):
    return conn.execute(
        "SELECT order_id, status, side, qty FROM paper_order WHERE user_id=%s AND reason LIKE 'flatten%%'",
        (key,),
    ).fetchall()


def test_flatten_makes_the_closing_order_from_the_accounts_own_book_and_leaves_it_for_the_live_process(
    env,
):
    conn, owner, key, iid, clock, broker, proc = env
    hold(conn, proc, broker, key, iid, 10)
    flatten_switch(conn)
    result = paper_oms.flatten(conn, OPEN)
    assert len(result.sent) == 1 and result.refused == []
    ((oid, status, side, qty),) = closing(conn, key)
    assert (status, side, qty) == ("APPROVED", "SELL", D(10))  # approved by the FLATTEN itself
    assert broker.place_calls == 1  # only the earlier buy: flatten never talks to the broker
    by = conn.execute("SELECT decided_by FROM paper_order WHERE order_id=%s", (oid,)).fetchone()
    assert by[0] == owner


def test_the_live_process_sends_the_closing_order_once_and_the_fill_empties_the_book(env):
    conn, owner, key, iid, clock, broker, proc = env
    hold(conn, proc, broker, key, iid, 10)
    flatten_switch(conn)
    paper_oms.flatten(conn, OPEN)
    paper_oms.flatten(
        conn, OPEN + timedelta(minutes=1)
    )  # the job runs every minute: no second order
    proc.tick()
    proc.tick()
    assert len(closing(conn, key)) == 1 and broker.place_calls == 2
    ((oid, *_),) = closing(conn, key)
    broker.move(client_order_id(STRATEGY, str(oid)), "COMPLETE", filled_qty=10, avg_price=D(210))
    proc.tick()
    assert book.load(conn, key).qty(iid) == 0
    assert closing(conn, key)[0][1] == "FILLED"


def test_flatten_cancels_what_else_was_open_but_never_the_closing_order(env):
    conn, owner, key, iid, clock, broker, proc = env
    hold(conn, proc, broker, key, iid, 10)
    _, working_tag = buy(conn, proc, key, iid, 5, decision_day=date(2026, 11, 11))  # still open
    working_broker_id = broker.book[working_tag].broker_order_id
    flatten_switch(conn)
    paper_oms.flatten(conn, OPEN)
    proc.tick()
    proc.tick()
    assert broker.cancel_calls == [working_broker_id]  # the working buy came off, the sell did not
    ((oid, *_),) = closing(conn, key)
    assert client_order_id(STRATEGY, str(oid)) in broker.book


def test_shares_the_owner_holds_by_hand_are_never_in_the_closing_order(env):
    conn, owner, key, iid, clock, broker, proc = env  # the live book holds nothing
    flatten_switch(conn)
    result = paper_oms.flatten(conn, OPEN)
    assert result.sent == [] and closing(conn, key) == [] and broker.place_calls == 0


def test_a_paper_account_still_closes_through_the_paper_path(env):
    conn, owner, key, iid, clock, broker, proc = env
    paper_owner = add_user(conn, SimClock(EVENING), "TRADER", "paper@example.com")
    book.create_account(
        conn,
        paper_owner,
        strategy_id=STRATEGY,
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    book.record_fill(
        conn, paper_owner, day=date(2026, 11, 3), side="BUY", iid=iid, qty=D(10), price=D(200),
        commission=D(0), charges=[], ref="p", now=EVENING,
    )  # fmt: skip
    flatten_switch(conn)
    result = paper_oms.flatten(conn, OPEN)
    row = conn.execute(
        "SELECT order_id, status FROM paper_order WHERE user_id=%s", (paper_owner,)
    ).fetchone()
    assert result.sent == [row[0]] and row[1] == "APPROVED"  # sent to the paper broker, as before
    assert broker.place_calls == 0  # and the live broker saw nothing

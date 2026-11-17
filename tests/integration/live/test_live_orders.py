# ruff: noqa: E501
"""One pipeline: a LIVE account's order is proposed, approved (risk checked) exactly like a paper one; only then the condition applies: approval queues it
and the live process sends it through its own OMS to the broker. Real Postgres, scripted broker."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.execution.event_store import DbStore
from algo.execution.kite_account import Account
from algo.execution.oms import Oms
from algo.live.process import LiveProcess
from algo.paper import book, orders
from algo.paper import risk as paper_risk
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.limits import Limits
from tests.support.fake_broker import FakeBroker
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)  # Friday 09:15 IST
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)


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
        strategy_id="trend_pullback",
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    conn.execute("UPDATE paper_account SET mode='LIVE' WHERE user_id=%s", (user,))
    return conn, user, iid, clock


def proposal(conn, user, iid, side="BUY", qty=10):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,200,'entry',%s,%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, side, qty, EVENING, OPEN, CLOSE),
    ).fetchone()[0]


def process(conn, clock, broker, limits=None):
    oms = Oms(
        broker,
        RiskEngine(limits or Limits(), risk_store.load(conn)),
        clock,
        store=DbStore(conn),
        own_positions_only=True,
    )
    return LiveProcess(oms, Reader(), {}, clock, conn, host="h", pid=1), oms


def row(conn, oid):
    return conn.execute(
        "SELECT status, failure FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone()


def test_approving_a_live_order_queues_it_and_sends_nothing(env):
    conn, user, iid, _ = env
    oid = proposal(conn, user, iid)
    orders.approve(conn, oid, user_id=user, now=OPEN)
    assert row(conn, oid)[0] == "APPROVED"
    assert (
        conn.execute("SELECT count(*) FROM oms_event").fetchone()[0] == 0
    )  # the API never talks to the broker


def test_the_live_process_sends_an_approved_order_once(env):
    conn, user, iid, clock = env
    broker = FakeBroker()
    oid = proposal(conn, user, iid)
    orders.approve(conn, oid, user_id=user, now=OPEN)
    proc, _ = process(conn, clock, broker)
    proc.start()
    proc.tick()
    proc.tick()
    assert broker.place_calls == 1
    assert row(conn, oid)[0] == "APPROVED"  # working at the broker


def test_risk_still_applies_and_a_refusal_fails_the_order_with_the_reason(env):
    conn, user, iid, clock = env
    broker = FakeBroker()
    oid = proposal(conn, user, iid)
    orders.approve(conn, oid, user_id=user, now=OPEN)
    risk_store.change(conn, "pause", None, by="o", reason="drill", now=OPEN)
    proc, _ = process(conn, clock, broker)
    proc.start()
    proc.tick()
    status, why = row(conn, oid)
    assert status == "FAILED" and "PAUSE" in why.upper()
    assert broker.place_calls == 0


def test_an_order_that_expired_before_the_process_sent_it_is_never_sent_late(env):
    conn, user, iid, clock = env
    broker = FakeBroker()
    oid = proposal(conn, user, iid)
    orders.approve(conn, oid, user_id=user, now=OPEN)
    clock.advance_to(CLOSE + timedelta(minutes=1))
    proc, _ = process(conn, clock, broker)
    proc.start()
    proc.tick()
    assert row(conn, oid) == ("FAILED", "expired before the live process sent it")
    assert broker.place_calls == 0


def test_a_sell_of_shares_the_platform_never_bought_is_refused(env):
    conn, user, iid, clock = env
    broker = FakeBroker()
    oid = proposal(
        conn, user, iid, side="SELL", qty=5
    )  # the owner holds them by hand; the platform's book holds none
    conn.execute(
        "UPDATE paper_order SET status='APPROVED', decided_at=%s, decided_by=%s WHERE order_id=%s",
        (OPEN, user, oid),
    )
    proc, _ = process(conn, clock, broker)
    proc.start()
    proc.tick()
    assert row(conn, oid)[0] == "FAILED" and broker.place_calls == 0


def test_the_risk_inputs_do_not_count_the_order_being_sent(env):
    conn, user, iid, _ = env
    oid = proposal(conn, user, iid)
    orders.approve(conn, oid, user_id=user, now=OPEN)
    _, _, state, day = paper_risk.inputs(conn, user, oid, OPEN)
    assert state.open_orders == 0 and day.orders == 0

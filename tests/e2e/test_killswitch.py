# ruff: noqa: E501
"""TODO 5.6 kill switch, end to end: the portal's switch (the same `risk_store.change` the /risk API calls) against a running live process, a real
Postgres and a scripted broker. What the owner clicks must reach the broker, and a restart must not undo it."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.execution.event_store import DbStore
from algo.execution.kite_account import Account
from algo.execution.oms import Oms
from algo.execution.orders import State
from algo.live.process import LiveProcess
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import FakeBroker

pytestmark = pytest.mark.e2e
OPEN = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST, a Monday


class Reader:
    def read(self):
        return Account(D(0), [], [])


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def process(db, broker, clock):
    oms = Oms(
        broker,
        RiskEngine(Limits(), risk_store.load(db)),
        clock,
        store=DbStore(db),
        own_positions_only=True,
    )
    return LiveProcess(oms, Reader(), {7: "INFY", 8: "TCS"}, clock, db, host="h", pid=1), oms


def order(oms, key, strategy="s1", instrument=7):
    return oms.submit(
        key, OrderRequest(strategy, instrument, Side.BUY, 10), Market(ltp=D(100)), Book(), Day()
    )


def portal(db, clock, op, scope=None):
    risk_store.change(db, op, scope, by="owner", reason="e2e", now=clock.now())
    clock.advance(timedelta(minutes=1))  # the next minute: the process looks again


def test_cancel_from_the_portal_cancels_the_open_orders_at_the_broker_once(db):
    clock, broker = SimClock(OPEN), FakeBroker()
    proc, oms = process(db, broker, clock)
    proc.start()
    first, second = order(oms, "a"), order(oms, "b", instrument=8)
    portal(db, clock, "cancel")
    proc.tick()
    proc.tick()  # the next tick must not ask again
    assert sorted(broker.cancel_calls) == sorted([first.broker_order_id, second.broker_order_id])
    assert order(oms, "c").state is State.REJECTED  # and nothing new goes out


def test_cancel_for_one_strategy_leaves_the_other_strategy_alone(db):
    clock, broker = SimClock(OPEN), FakeBroker()
    proc, oms = process(db, broker, clock)
    proc.start()
    mine, other = order(oms, "a", "s1"), order(oms, "b", "s2", 8)
    portal(db, clock, "cancel", "s1")
    proc.tick()
    assert broker.cancel_calls == [mine.broker_order_id]
    assert order(oms, "c", "s2", 8).state is not State.REJECTED
    assert other.broker_order_id not in broker.cancel_calls


def test_a_pause_survives_a_restart_and_a_resume_lifts_it(db):
    clock, broker = SimClock(OPEN), FakeBroker()
    proc, oms = process(db, broker, clock)
    proc.start()
    portal(db, clock, "pause")
    proc.tick()
    assert order(oms, "a").state is State.REJECTED
    proc2, oms2 = process(db, broker, clock)  # the process is restarted
    proc2.start()
    assert (
        order(oms2, "b").state is State.REJECTED
    )  # still paused: the switch lives in the database
    portal(db, clock, "resume")
    proc2.tick()
    assert order(oms2, "c").state is State.SUBMITTED
    assert risk_store.load(db).mode("s1") is Mode.RUNNING


def test_a_cancel_that_fails_at_the_broker_is_tried_again_next_tick(db):
    clock, broker = SimClock(OPEN), FakeBroker()
    proc, oms = process(db, broker, clock)
    proc.start()
    placed = order(oms, "a")
    portal(db, clock, "cancel")
    broker.cancel_fails = True
    proc.tick()
    broker.cancel_fails = False
    proc.tick()
    assert broker.cancel_calls == [placed.broker_order_id] * 2
    proc.tick()
    assert len(broker.cancel_calls) == 2  # asked once it worked, not again

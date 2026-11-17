# ruff: noqa: E501
"""TODO 5.6 restart recovery, end to end: a live process dies at the worst moments and a new one starts on the same database. Real Postgres,
a scripted broker that keeps its orders across the restart (the broker does not restart). Never a duplicate order, never a lost one."""

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.execution.event_store import DbStore
from algo.execution.kite_account import Account, HoldingRow
from algo.execution.oms import Oms
from algo.execution.orders import State
from algo.live import heartbeat
from algo.live.process import LiveProcess
from algo.risk import store as risk_store
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import Crash, FakeBroker

pytestmark = pytest.mark.e2e
OPEN = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST, a Monday


class Reader:
    def __init__(self, held=0):
        self.held = held

    def read(self):
        rows = [HoldingRow("INFY", "NSE", self.held, 0, D(1), D(1), D(0))] if self.held else []
        return Account(D(0), rows, [])


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def process(db, broker, held=0):
    clock = SimClock(OPEN)
    oms = Oms(
        broker,
        RiskEngine(Limits(), risk_store.load(db)),
        clock,
        store=DbStore(db),
        own_positions_only=True,
    )
    return LiveProcess(oms, Reader(held), {7: "INFY"}, clock, db, host="h", pid=1), oms


def buy(oms, key):
    return oms.submit(key, OrderRequest("s1", 7, Side.BUY, 10), Market(ltp=D(100)), Book(), Day())


def rows(db):
    return db.execute("SELECT count(DISTINCT order_id) FROM oms_event").fetchone()[0]


def test_a_restart_with_open_and_part_filled_orders_loses_none_and_resends_none(db):
    broker = FakeBroker()
    proc, oms = process(db, broker)
    proc.start()
    done, part, open_ = buy(oms, "a"), buy(oms, "b"), buy(oms, "c")
    oms.on_update(broker.move(done.order_id, "COMPLETE", filled_qty=10, avg_price=D(100)))
    oms.on_update(broker.move(part.order_id, "OPEN", filled_qty=4, avg_price=D(100)))
    proc2, oms2 = process(db, broker, held=14)  # the first process is gone
    proc2.start()
    assert proc2.tick() == []  # reconciles clean against the broker
    assert broker.place_calls == 3 and rows(db) == 3
    assert sorted(o.filled_qty for o in oms2.orders.values()) == [0, 4, 10]
    assert oms2.orders[done.order_id].state is State.FILLED
    assert oms2.orders[open_.order_id].is_open
    assert heartbeat.load(db)["live"].state == "RUNNING"


def test_death_after_the_broker_took_the_order_finds_it_and_sends_nothing_twice(db):
    broker = FakeBroker(["crash_after"])
    _, first = process(db, broker)
    with pytest.raises(Crash):
        buy(first, "a")
    proc, oms = process(db, broker)
    proc.start()
    assert broker.place_calls == 1 and rows(db) == 1
    assert next(iter(oms.orders.values())).state is State.ACKED
    assert proc.tick() == []
    again = buy(oms, "a")  # the strategy asks for the same intent again after the restart
    assert broker.place_calls == 1 and again.state is State.ACKED


def test_death_before_the_order_left_does_not_send_it_blind_and_pauses_the_strategy(db):
    broker = FakeBroker(["crash_before"])
    _, first = process(db, broker)
    with pytest.raises(Crash):
        buy(first, "a")
    proc, oms = process(db, broker)
    proc.start()
    (order,) = oms.orders.values()
    assert order.state is State.UNKNOWN  # an ATTEMPT was logged, the broker has nothing: not resent
    assert broker.place_calls == 1
    assert (
        risk_store.load(db).mode("s1") is not Mode.RUNNING
    )  # persisted, so the next restart is paused too
    proc.tick()
    assert heartbeat.load(db)["live"].state in ("RUNNING", "DEGRADED")

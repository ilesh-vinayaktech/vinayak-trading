# ruff: noqa: E501
"""TODO 5.3 live process: what runs the OMS pieces that were only ever called by tests. Real Postgres, FakeBroker (the component under test is the process, not the broker)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.execution.broker import BrokerError
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

pytestmark = pytest.mark.integration
OPEN = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST, a Monday
AFTER_CLOSE = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)  # 16:30 IST
SYMBOLS = {7: "INFY"}


class Reader:
    def __init__(self, held=0, fails=False):
        self.held, self.fails, self.reads = held, fails, 0

    def read(self):
        self.reads += 1
        if self.fails:
            raise BrokerError("token expired")
        rows = [HoldingRow("INFY", "NSE", self.held, 0, D(1), D(1), D(0))] if self.held else []
        return Account(D(0), rows, [])


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


def build(db, broker, reader, now=OPEN):
    clock = SimClock(now)
    oms = Oms(
        broker,
        RiskEngine(Limits(), risk_store.load(db)),
        clock,
        store=DbStore(db),
        own_positions_only=True,
    )
    return LiveProcess(oms, reader, SYMBOLS, clock, db, host="h", pid=1), clock, oms


def buy(oms, key="k1", qty=10):
    return oms.submit(key, OrderRequest("s1", 7, Side.BUY, qty), Market(ltp=D(100)), Book(), Day())


def beat_of(db):
    return heartbeat.load(db)["live"]


def test_start_recovers_an_order_a_crash_left_in_the_air_and_never_resends_it(db):
    broker = FakeBroker(["crash_after"])
    _, _, first = build(db, broker, Reader())
    with pytest.raises(Crash):
        buy(first)
    proc, _, oms = build(db, broker, Reader())  # a new process on the same database
    proc.start()
    (order,) = oms.orders.values()
    assert order.state is State.ACKED  # found at the broker by its tag, adopted, not resent
    assert broker.place_calls == 1
    assert beat_of(db).state == "RUNNING"


def test_a_minute_in_session_reconciles_and_a_clean_book_stays_running(db):
    proc, _, _ = build(db, FakeBroker(), Reader())
    proc.start()
    assert proc.tick() == []
    assert risk_store.load(db).mode("s1") is Mode.RUNNING
    assert beat_of(db).state == "RUNNING"


def test_a_mismatch_pauses_trading_in_the_database_and_reports_degraded(db):
    broker = FakeBroker()
    proc, _, oms = build(db, broker, Reader(held=0))
    proc.start()
    order = buy(oms)
    oms.on_update(broker.move(order.order_id, "COMPLETE", filled_qty=10, avg_price=D(100)))
    found = proc.tick()  # the OMS bought 10; the account holds none of it
    assert found
    assert (
        risk_store.load(db).mode("s1") is not Mode.RUNNING
    )  # persisted, so a restart stays paused
    assert beat_of(db).state == "DEGRADED"


def test_an_unreadable_account_halts_and_the_next_tick_does_not_repeat_the_pause(db):
    proc, clock, _ = build(db, FakeBroker(), Reader(fails=True))
    proc.start()
    proc.tick()
    n = len(risk_store.load(db).events)
    assert n >= 1 and risk_store.load(db).mode("s1") is not Mode.RUNNING
    clock.advance(timedelta(minutes=2))
    proc.tick()
    assert len(risk_store.load(db).events) == n  # an escalation already in force is written once


def test_a_pause_from_the_portal_reaches_the_running_process(db):
    proc, clock, oms = build(db, FakeBroker(), Reader())
    proc.start()
    risk_store.change(db, "pause", None, by="owner", reason="drill", now=clock.now())
    clock.advance(timedelta(minutes=1))
    proc.tick()
    assert oms.risk.switch.mode("s1") is Mode.PAUSE
    assert buy(oms).state is State.REJECTED  # the running process obeys it without a restart


def test_after_the_close_one_final_pass_runs_and_then_the_process_idles(db):
    reader = Reader()
    proc, clock, _ = build(db, FakeBroker(), reader)
    proc.start()
    clock.advance_to(AFTER_CLOSE)
    proc.tick()
    proc.tick()
    assert reader.reads == 1  # the post-close pass happens once per day
    assert beat_of(db).state == "RUNNING"


def test_ticks_inside_the_same_minute_do_not_reconcile_twice(db):
    reader = Reader()
    proc, clock, _ = build(db, FakeBroker(), reader)
    proc.start()
    proc.tick()
    clock.advance(timedelta(seconds=20))
    proc.tick()
    clock.advance(timedelta(seconds=45))
    proc.tick()
    assert reader.reads == 2


def test_stop_writes_a_stopped_beat(db):
    proc, _, _ = build(db, FakeBroker(), Reader())
    proc.start()
    proc.stop()
    assert beat_of(db).state == "STOPPED"

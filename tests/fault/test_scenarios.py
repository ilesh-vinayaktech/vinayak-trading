# ruff: noqa: E501
"""Fault injection (docs: TODO 5.4). Each scenario breaks something on purpose and asserts what must stay true: no duplicate orders, the
order log consistent, the platform degrading as designed, and recovery reaching a trading state only after the checks pass.
Not applicable: "stop Redis" (messaging is Postgres and Redis is not used: docs/TODO 5.3), "disconnect the broker WebSocket" (covered
at the feed with a scripted socket: tests/integration/test_feed.py, silent connection, reconnect back-off, no volume dumped in a bar)."""

import errno
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import psycopg
import pytest

from algo.core.clock import SimClock
from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate
from algo.execution.broker import BrokerTimeout
from algo.execution.event_store import DbStore
from algo.execution.oms import Oms
from algo.execution.orders import State
from algo.live import heartbeat
from algo.live.consumer import data_fresh
from algo.platform_state import store as platform_store
from algo.platform_state.boot import Probe, Probes, boot
from algo.platform_state.machine import State as Platform
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch, Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import Crash, FakeBroker

pytestmark = [pytest.mark.fault, pytest.mark.integration]
NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST
MKT, BOOK, DAY = Market(ltp=D(100)), Book(), Day()


@pytest.fixture
def env(conn):
    migrate(conn)
    return conn


def oms_on(connection, broker, switch=None, clock=None, limits=None):
    return Oms(
        broker,
        RiskEngine(limits or Limits(), switch or KillSwitch()),
        clock or SimClock(NOW),
        store=DbStore(connection),
    )


def submit(oms, key, qty=10, strategy="s1"):
    return oms.submit(key, OrderRequest(strategy, 7, Side.BUY, qty), MKT, BOOK, DAY)


def log_is_contiguous(conn):
    rows = conn.execute("SELECT order_id, seq FROM oms_event ORDER BY order_id, seq").fetchall()
    by = {}
    for oid, seq in rows:
        by.setdefault(oid, []).append(seq)
    return all(seqs == list(range(len(seqs))) for seqs in by.values())


# 1. kill the OMS mid-submission ------------------------------------------------------------------------------------------
def test_the_oms_dies_after_the_broker_took_the_order_and_the_restart_finds_it_without_a_second_one(
    env,
):
    broker = FakeBroker(["crash_after"])
    with pytest.raises(Crash):
        submit(oms_on(env, broker), "k1")
    assert len(broker.book) == 1  # the broker has the order, the OMS never heard
    again = oms_on(env, broker)
    again.recover()
    (order,) = again.orders.values()
    assert (
        order.state is State.ACKED and broker.place_calls == 1 and len(broker.book) == 1
    )  # found by its tag, never resent
    assert (
        submit(again, "k1").order_id == order.order_id and broker.place_calls == 1
    )  # the same intent again: still one
    assert log_is_contiguous(env) and not again.alerts


def test_the_oms_dies_before_the_order_left_and_the_restart_pauses_the_strategy_instead_of_guessing(
    env,
):
    broker = FakeBroker(["crash_before"])
    with pytest.raises(Crash):
        submit(oms_on(env, broker), "k1")
    switch = KillSwitch()
    again = oms_on(env, broker, switch)
    again.recover()
    (order,) = again.orders.values()
    assert (
        order.state is State.UNKNOWN and len(broker.book) == 0 and broker.place_calls == 1
    )  # not resent: it may have been sent
    assert (
        switch.mode("s1") is not Mode.RUNNING and again.alerts and log_is_contiguous(env)
    )  # DEGRADED by design: paused and alerted


# 2. Postgres lost mid-submission, then back -------------------------------------------------------------------------------
def test_the_database_connection_is_lost_while_the_order_is_being_sent_and_a_new_connection_recovers_cleanly(
    env, pg_url
):
    victim = psycopg.connect(pg_url, autocommit=True)

    class Killer(FakeBroker):
        def place_order(self, req, client_order_id):
            super().place_order(req, client_order_id)  # the broker has it
            env.execute(
                "SELECT pg_terminate_backend(%s)", (victim.info.backend_pid,)
            )  # and the database drops the OMS's connection
            raise BrokerTimeout("no reply")

    broker = Killer()
    with pytest.raises(psycopg.OperationalError):
        submit(oms_on(victim, broker), "k1")
    fresh = psycopg.connect(pg_url, autocommit=True)
    again = oms_on(fresh, broker)
    again.recover()
    (order,) = again.orders.values()
    assert order.state is State.ACKED and len(broker.book) == 1 and broker.place_calls == 1
    assert log_is_contiguous(fresh)
    fresh.close()


# 3. duplicate and out-of-order broker callbacks ---------------------------------------------------------------------------
def test_duplicate_and_out_of_order_callbacks_never_double_count_a_fill_and_a_replay_agrees(env):
    broker = FakeBroker()
    oms = oms_on(env, broker)
    o = submit(oms, "k1", qty=10)
    for status, filled in (
        ("PARTIAL", 4),
        ("COMPLETE", 10),
        ("PARTIAL", 4),
        ("OPEN", 0),
        ("COMPLETE", 10),
        ("COMPLETE", 10),
    ):
        oms.on_update(broker.move(o.order_id, status, filled, D(100)))
    assert oms.orders[o.order_id].state is State.FILLED and oms.orders[o.order_id].filled_qty == 10
    assert oms.positions() == {("s1", 7): 10}  # bought once, not twice
    assert oms.ignored >= 3
    replay = oms_on(env, FakeBroker())
    assert (
        replay.orders == oms.orders and replay.positions() == oms.positions()
    )  # the log alone rebuilds the same orders


# 4. restart with orders still open ---------------------------------------------------------------------------------------
def test_a_restart_with_open_and_part_filled_orders_loses_none_repeats_none_and_reconciles_clean(
    env,
):
    broker = FakeBroker()
    oms = oms_on(env, broker)
    a, b, c = (submit(oms, k) for k in ("a", "b", "c"))
    oms.on_update(broker.move(b.order_id, "PARTIAL", 4, D(100)))
    restarted = oms_on(env, broker)  # a new process, nothing in memory
    assert {o.order_id: o.state for o in restarted.orders.values()} == {
        a.order_id: State.SUBMITTED, b.order_id: State.PARTIALLY_FILLED, c.order_id: State.SUBMITTED,
    }  # fmt: skip
    assert restarted.reconcile() == []  # the broker agrees with the log
    for key in ("a", "b", "c"):
        submit(restarted, key)  # the same intents again
    assert broker.place_calls == 3  # none was sent a second time
    restarted.on_update(broker.move(b.order_id, "COMPLETE", 10, D(100)))
    assert restarted.positions() == {("s1", 7): 10} and log_is_contiguous(env)


# 5. clock skew ----------------------------------------------------------------------------------------------------------
def test_a_clock_that_jumps_around_the_open_neither_lets_an_early_order_through_nor_breaks_the_log(
    env,
):
    from datetime import time

    limits = Limits(trading_hours=(time(9, 15), time(15, 30)))
    before_open = datetime(2026, 11, 16, 3, 44, 30, tzinfo=UTC)  # 09:14:30 IST
    clock = SimClock(before_open)
    oms = oms_on(env, FakeBroker(), clock=clock, limits=limits)
    assert (
        submit(oms, "early").state is State.REJECTED
    )  # the risk engine's hours check uses the (skewed) clock honestly
    clock.advance_to(datetime(2026, 11, 16, 3, 45, 0, tzinfo=UTC))
    assert submit(oms, "on_time").state is State.SUBMITTED
    stamps = [r[0] for r in env.execute("SELECT ts FROM oms_event ORDER BY order_id, seq")]
    assert stamps  # a clock that later steps back only affects timestamps: the log orders events by sequence, so replay is unaffected
    assert (
        oms_on(
            env, FakeBroker(), clock=SimClock(before_open - timedelta(hours=1)), limits=limits
        ).orders
        == oms.orders
    )


def test_a_clock_behind_the_feed_is_flagged_instead_of_making_stale_data_look_fresh(env):
    env.execute(
        "INSERT INTO feed_status (feed_id, state, detail, subscribed, last_bar_at, ticks_total, bars_total, bad_frames, late_ticks, updated_at)"
        " VALUES (1, 'CONNECTED', '', 10, %s, 0, 0, 0, 0, %s)",
        (NOW + timedelta(minutes=10), NOW + timedelta(minutes=10)),
    )
    reason = data_fresh(env, NOW, timedelta(minutes=3))
    assert reason is not None and "clock" in reason and "behind" in reason


def test_a_heartbeat_dated_in_the_future_is_clock_skew_not_a_healthy_process():
    future = {"feed": heartbeat.Beat("feed", "RUNNING", "", NOW + timedelta(minutes=10))}
    (problem,) = heartbeat.assess(
        future, [heartbeat.DEFAULT_EXPECTED["feed"]], NOW, in_session=True
    )
    assert "clock" in problem and "ahead" in problem


# 6. disk full on the raw lake ---------------------------------------------------------------------------------------------
def test_a_full_disk_in_the_middle_of_a_lake_write_leaves_nothing_behind_and_the_retry_succeeds(
    tmp_path, monkeypatch
):
    lake = LocalLake(tmp_path)
    real_open = open

    def full_disk(path, mode="r", *a, **kw):
        f = real_open(path, mode, *a, **kw)
        if "b" in mode and "x" in mode:
            f.write(b"par")  # a few bytes land, then the disk is full

            def explode(*_a, **_k):
                raise OSError(errno.ENOSPC, "No space left on device")

            f.write = explode
        return f

    monkeypatch.setattr("algo.data.lake.open", full_disk, raising=False)
    with pytest.raises(OSError):
        lake.put("nse", "bhavcopy", date(2026, 11, 13), b"the whole file", url="u", fetched_at=NOW)
    monkeypatch.undo()
    assert (
        lake.versions("nse", "bhavcopy", date(2026, 11, 13)) == []
    )  # no half-written version is visible
    m = lake.put(
        "nse", "bhavcopy", date(2026, 11, 13), b"the whole file", url="u", fetched_at=NOW
    )  # the retry is not blocked by debris
    assert m.version == 1 and lake.get(m) == b"the whole file"


# 7. recovery reaches a trading state only after reconciliation -----------------------------------------------------------
def test_after_a_failure_the_platform_trades_again_only_once_every_reconciliation_check_passes(env):
    def probes(**over):
        ok = lambda: Probe(True, "ok")  # noqa: E731
        base = dict(
            market_data_fresh=ok,
            broker_session_valid=ok,
            orders_reconciled=ok,
            positions_reconciled=ok,
            cash_reconciled=ok,
            portfolio_loaded=ok,
        )
        return Probes(**{**base, **over})

    platform_store.record_halt(env, NOW, "reconciliation mismatch: instrument 7")
    assert platform_store.trading_blocked(env, NOW) is not None
    still = boot(env, NOW + timedelta(minutes=1), probes(), operator=False)
    assert still.state is Platform.HALTED  # a restart does not clear a halt
    mismatch = boot(
        env,
        NOW + timedelta(minutes=2),
        probes(orders_reconciled=lambda: Probe(False, "1 order differs")),
        operator=True,
    )
    assert (
        mismatch.state is Platform.RECOVERY
        and platform_store.trading_blocked(env, NOW + timedelta(minutes=2)) is not None
    )
    healed = boot(env, NOW + timedelta(minutes=3), probes(), operator=True)
    assert (
        healed.state is Platform.PAPER
        and platform_store.trading_blocked(env, NOW + timedelta(minutes=3)) is None
    )

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.platform_state import store
from algo.platform_state.boot import Probe, Probes, boot
from algo.platform_state.machine import State

pytestmark = pytest.mark.integration
MORNING = datetime(2026, 11, 16, 3, 20, tzinfo=UTC)  # 08:50 IST


def ok(why="ok"):
    return lambda: Probe(True, why)


def bad(why):
    return lambda: Probe(False, why)


def probes(**over):
    base = {
        "market_data_fresh": ok(), "broker_session_valid": ok(), "orders_reconciled": ok(),
        "positions_reconciled": ok(), "cash_reconciled": ok(), "portfolio_loaded": ok(),
    }  # fmt: skip
    return Probes(**{**base, **over})


@pytest.fixture
def env(conn):
    migrate(conn)
    return conn


def moves(conn):
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT from_state, to_state FROM platform_state_event ORDER BY event_id"
        )
    ]


def test_a_boot_with_every_check_passing_walks_the_machine_to_paper_and_records_each_step(env):
    r = boot(env, MORNING, probes())
    assert r.state is State.PAPER and r.failed == []
    assert moves(env) == [
        ("INITIALIZING", "DATA_VALIDATION"),
        ("DATA_VALIDATION", "READY"),
        ("READY", "PAPER"),
    ]
    assert store.latest(env)[0] is State.PAPER
    assert store.trading_blocked(env, MORNING + timedelta(hours=5)) is None


def test_one_failed_check_leaves_the_platform_in_recovery_and_says_which(env):
    r = boot(
        env,
        MORNING,
        probes(
            orders_reconciled=bad("2 orders differ from the broker"),
            market_data_fresh=bad("data is stale"),
        ),
    )
    assert r.state is State.RECOVERY
    assert sorted(r.failed) == [
        "market_data_fresh: data is stale",
        "orders_reconciled: 2 orders differ from the broker",
    ]
    assert moves(env) == [("INITIALIZING", "DATA_VALIDATION"), ("DATA_VALIDATION", "RECOVERY")]
    assert "RECOVERY" in store.trading_blocked(env, MORNING)


def test_a_check_that_crashes_counts_as_failed_it_never_passes_silently(env):
    def explode():
        raise RuntimeError("the broker session probe blew up")

    r = boot(env, MORNING, probes(broker_session_valid=explode))
    assert r.state is State.RECOVERY and r.failed == [
        "broker_session_valid: the probe raised: the broker session probe blew up"
    ]


def test_live_is_refused_unless_it_is_enabled_and_the_platform_stays_ready_not_live(env):
    r = boot(env, MORNING, probes(), mode=State.LIVE, live_enabled=False)
    assert r.state is State.READY and r.failed == ["live not enabled"]
    assert store.trading_blocked(env, MORNING) is not None
    assert (
        boot(
            env, MORNING + timedelta(minutes=1), probes(), mode=State.LIVE, live_enabled=True
        ).state
        is State.LIVE
    )


def test_every_boot_starts_from_initializing_so_a_restart_never_trades_on_yesterdays_state(env):
    boot(env, MORNING, probes())
    boot(
        env, MORNING + timedelta(days=1), probes(portfolio_loaded=bad("the order log did not load"))
    )
    assert store.latest(env)[0] is State.RECOVERY  # yesterday's PAPER does not carry over
    assert moves(env)[3] == ("INITIALIZING", "DATA_VALIDATION")


def test_a_boot_is_good_only_for_the_day_it_ran(env):
    boot(env, MORNING, probes())
    assert (
        store.trading_blocked(env, MORNING + timedelta(hours=14)) is None
    )  # the 21:30 IST run, same day
    assert "2026-11-16" in store.trading_blocked(env, MORNING + timedelta(days=1))


def test_a_halted_platform_is_not_restarted_by_a_boot_only_an_operator_can_clear_it(env):
    boot(env, MORNING, probes())
    halted = store.record_halt(
        env, MORNING + timedelta(hours=1), "kill switch: reconciliation mismatch"
    )
    assert halted is State.HALTED
    again = boot(env, MORNING + timedelta(hours=2), probes())
    assert again.state is State.HALTED and "operator" in again.failed[0]
    cleared = boot(env, MORNING + timedelta(hours=3), probes(), operator=True)
    assert cleared.state is State.PAPER


def test_the_log_cannot_be_changed_or_deleted(env):
    boot(env, MORNING, probes())
    for sql in ("UPDATE platform_state_event SET reason = 'x'", "DELETE FROM platform_state_event"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            env.execute(sql)


def test_nothing_recorded_yet_means_trading_is_blocked(env):
    assert store.latest(env) is None
    assert "no platform boot" in store.trading_blocked(env, MORNING)


def test_halting_an_already_halted_platform_changes_nothing_and_a_platform_with_no_history_can_be_halted(
    env,
):
    assert (
        store.record_halt(env, MORNING, "kill switch before any boot") is State.HALTED
    )  # no history: starts from INITIALIZING
    assert moves(env) == [("INITIALIZING", "HALTED")]
    assert (
        store.record_halt(env, MORNING + timedelta(minutes=1), "again") is State.HALTED
    )  # already halted
    assert moves(env) == [("INITIALIZING", "HALTED")]  # nothing was added

"""Each misbehaving strategy is stopped without hurting the platform: the call raises, the strategy is halted, and a fresh
worker for an honest strategy still works afterwards."""

import os
from decimal import Decimal as D

import pytest

from algo.sandbox.host import (
    Limits,
    SandboxCrash,
    SandboxMemoryError,
    SandboxTimeout,
    SandboxViolationError,
    StrategyFailed,
    StrategyHalted,
)
from tests.unit.sandbox.helpers import ROOT, adversarial, ctx, sandbox


def run(s, method="on_schedule"):
    try:
        return s.call(method, ctx())
    finally:
        s.stop()


def assert_platform_healthy():
    assert run(adversarial("Honest")) == {1: D("0.5")}


def test_an_honest_strategy_gets_its_targets_and_a_print_cannot_break_the_protocol():
    s = adversarial("Honest")
    assert s.call("on_schedule", ctx()) == {1: D("0.5")}
    assert s.identity == {"id": "adversarial", "version": "1"}
    assert s.call("universe", ctx()) == [1] and s.call("requirements", ctx()) == {
        "lookback_days": 365,
        "adjust": "split",
    }
    assert s.call("on_start", ctx()) is None
    s.stop()


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("OpensASocket", "network"),
        ("ReadsSecrets", "outside the allowed paths"),
        ("WritesAFile", "write files"),
        ("RunsACommand", "processes"),
        ("ForkBomb", "processes"),
        (
            "SwallowsTheViolation",
            "outside the allowed paths",
        ),  # it caught the exception: still reported
        ("ReadsTheClockSneakily", "system clock"),
    ],
)
def test_a_rule_breaking_strategy_is_stopped_halted_and_the_platform_carries_on(name, text):
    halted = []
    s = adversarial(name, on_halt=halted.append)
    with pytest.raises(SandboxViolationError, match=text):
        s.call("on_schedule", ctx())
    assert s.failed and s.failed.startswith("violation") and halted == [s.failed]
    with pytest.raises(StrategyHalted):
        s.call("on_schedule", ctx())  # a halted strategy gets no more calls
    assert not os.path.exists("/tmp/sandbox-escape.txt")
    assert_platform_healthy()


def test_the_project_secrets_file_cannot_be_read():
    from tests.support.adversarial import ReadsTheProjectEnvFile

    ReadsTheProjectEnvFile.path = str(ROOT / ".env")
    s = adversarial("ReadsTheProjectEnvFile")
    with pytest.raises(SandboxViolationError, match="outside the allowed paths"):
        run(s)


def test_a_strategy_that_reads_the_system_clock_is_refused_before_it_runs():
    s = sandbox("tests.support.adversarial_clock:ReadsTheClock")
    with pytest.raises(SandboxViolationError, match="ctx.now"):
        s.call("on_schedule", ctx())
    assert s.failed and s.identity == {}
    s.stop()


def test_the_worker_has_no_environment_so_no_secret_to_find():
    assert run(adversarial("ReadsEnvironment")) == {1: D(0)}


def test_the_database_cannot_be_reached_from_a_strategy():
    # psycopg cannot be imported by a strategy; and the network namespace leaves no route for native code either
    with pytest.raises(SandboxViolationError, match="import of psycopg"):
        run(adversarial("ConnectsToTheDatabase"))


def test_an_endless_loop_is_killed_at_the_deadline():
    s = adversarial("SpinsForever", limits=Limits(call_timeout_s=1.5))
    proc = None
    with pytest.raises(SandboxTimeout, match="no answer within 1.5"):
        s.call("on_schedule", ctx())
        proc = s._proc  # pragma: no cover
    assert s.failed.startswith("timeout") and s._proc is None
    assert_platform_healthy()
    assert proc is None


def test_a_strategy_that_eats_memory_is_stopped_by_the_memory_limit():
    s = adversarial("EatsMemory", limits=Limits(call_timeout_s=20.0, memory_bytes=1536 * 1024**2))
    with pytest.raises(SandboxMemoryError):
        s.call("on_schedule", ctx())
    assert s.failed.startswith("memory")
    assert_platform_healthy()


def test_a_worker_that_dies_is_a_crash_with_its_exit_code_and_the_strategy_is_halted():
    s = adversarial("DiesSuddenly")
    with pytest.raises(SandboxCrash, match="exit code 3"):
        s.call("on_schedule", ctx())
    assert s.failed.startswith("crash")
    assert_platform_healthy()


def test_an_ordinary_bug_fails_that_call_only_the_worker_and_strategy_stay_usable():
    s = adversarial("RaisesNormally")
    with pytest.raises(StrategyFailed, match="ValueError: a plain bug"):
        s.call("on_schedule", ctx())
    assert (
        s.failed is None and s._proc is not None
    )  # the strategy is not halted for a Python exception
    with pytest.raises(StrategyFailed):
        s.call("on_schedule", ctx())
    s.stop()


def test_a_strategy_returns_targets_or_nothing_never_anything_else():
    with pytest.raises(StrategyFailed, match="returns Targets"):
        run(adversarial("ReturnsGarbage"))


def test_a_strategy_that_cannot_be_loaded_is_reported_not_hung():
    with pytest.raises(StrategyFailed, match="cannot load"):
        sandbox("tests.support.adversarial:NoSuchClass").start()
    with pytest.raises(StrategyFailed, match="cannot load"):
        sandbox("no_such_module:X").start()

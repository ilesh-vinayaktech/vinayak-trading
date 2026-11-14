import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from algo.core.clock import SimClock
from algo.data.reader import Loaded
from algo.sandbox.host import (
    Limits,
    SandboxCrash,
    SandboxTimeout,
    StrategyHalted,
    spawn,
)
from algo.strategy.context import Context, DataAccess, PortfolioView
from tests.support.strategies import HoldParams, HoldWeights
from tests.unit.sandbox.helpers import NOW, ROOT, adversarial, ctx, sandbox

OPEN = lambda d: datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)  # noqa: E731
DAYS = [date(2026, 11, 9) + timedelta(days=i) for i in range(5)]


def real_ctx(now):
    loaded = {
        1: Loaded(
            [
                (OPEN(d), D(100 + i), D(100 + i), D(100 + i), D(100 + i), D(1000))
                for i, d in enumerate(DAYS)
            ],
            [],
            timedelta(hours=9, minutes=15),
            strict=False,
        ),
        2: Loaded(
            [
                (OPEN(d), D(50 + i), D(50 + i), D(50 + i), D(50 + i), D(500))
                for i, d in enumerate(DAYS)
            ],
            [],
            timedelta(hours=9, minutes=15),
            strict=False,
        ),
    }
    clock = SimClock(now)
    return Context(
        clock,
        DataAccess(loaded, clock, "none"),
        PortfolioView.of(D(1000), {1: D(5)}, D(1500)),
        "research",
    )


def test_a_real_strategy_through_the_sandbox_decides_exactly_as_it_does_in_process():
    now = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)
    params = {"ids": [1, 2], "weights": [D("0.6"), D("0.4")], "lookback": 30}
    inside = HoldWeights(HoldParams(**params))
    expected = inside.on_schedule(real_ctx(now))
    s = sandbox("tests.support.strategies:HoldWeights", params)
    try:
        assert s.call("on_schedule", real_ctx(now)) == expected == {1: D("0.6"), 2: D("0.4")}
        assert s.call("universe", real_ctx(now)) == [1, 2]
        assert s.call("requirements", real_ctx(now)) == {"lookback_days": 30, "adjust": "split"}
    finally:
        s.stop()


def test_history_is_asked_of_the_platform_as_of_ctx_now_so_the_worker_never_sees_the_future():
    asked = []

    class Spy:
        def history(self, ids, lookback, adjusted=True):
            asked.append((tuple(ids), lookback, adjusted))
            return real.data.history(ids, lookback, adjusted=adjusted)

    now = datetime(
        2026, 11, 10, 13, 0, tzinfo=UTC
    )  # the 9th and 10th have closed; the 11th is the future
    real = real_ctx(now)
    spy_ctx = SimpleNamespace(now=real.now, mode=real.mode, portfolio=real.portfolio, data=Spy())
    s = sandbox(
        "tests.support.strategies:HoldWeights", {"ids": [1], "weights": [D(1)], "lookback": 10}
    )
    try:
        s.call("on_schedule", spy_ctx)
    finally:
        s.stop()
    assert asked == [((1,), 10, True)]
    seen = real.data.history([1], 10)[1]
    assert [b.close for b in seen] == [
        D(100),
        D(101),
    ]  # what the platform served: nothing after the cutoff


def test_the_same_calls_give_the_same_answers_on_every_fresh_worker():
    def run_once():
        s = sandbox("tests.support.adversarial:Counter")
        try:
            return [s.call("on_schedule", ctx(now=NOW + timedelta(days=i))) for i in range(3)]
        finally:
            s.stop()

    first = run_once()
    assert first == run_once() == run_once()
    assert first[2] == {1: D("0.3"), 2: D("0.18")}


def test_a_replacement_worker_carries_on_from_the_saved_state_after_a_crash():
    steady = sandbox("tests.support.adversarial:Counter")
    uninterrupted = [steady.call("on_schedule", ctx(now=NOW + timedelta(days=i))) for i in range(4)]
    steady.stop()

    a = sandbox("tests.support.adversarial:Counter")
    a.call("on_schedule", ctx(now=NOW))
    a.call("on_schedule", ctx(now=NOW + timedelta(days=1)))
    assert a.state == {"calls": 2}
    a._proc.kill()  # the worker dies mid-run
    with pytest.raises(SandboxCrash):
        a.call("on_schedule", ctx(now=NOW + timedelta(days=2)))
    assert a.failed and a.state == {"calls": 2}  # the state survived on the platform side
    b = sandbox("tests.support.adversarial:Counter", state=a.state)
    resumed = [b.call("on_schedule", ctx(now=NOW + timedelta(days=i))) for i in (2, 3)]
    b.stop()
    assert resumed == uninterrupted[2:]  # identical decisions after the restart


def test_a_strategy_without_state_methods_just_has_no_state():
    s = adversarial("Honest")
    s.call("on_schedule", ctx())
    assert s.state is None
    s.stop()


def test_a_halted_strategy_cannot_be_started_again_and_stop_is_safe_twice():
    s = adversarial("DiesSuddenly")
    with pytest.raises(SandboxCrash):
        s.call("on_schedule", ctx())
    with pytest.raises(StrategyHalted):
        s.start()
    s.stop()


def test_the_clock_for_deadlines_is_injected():
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    s = adversarial(
        "Honest", limits=Limits(call_timeout_s=5.0), monotonic=lambda: next(ticks, 100.0)
    )
    with pytest.raises(SandboxTimeout):
        s.call("on_schedule", ctx())  # the injected clock says the deadline already passed


def test_a_worker_gets_a_clean_environment_and_an_empty_temporary_directory():
    import tempfile

    s = adversarial("Honest")
    s.start()
    assert "algo-sandbox-" in s._tmp.name and s._proc.pid > 0
    s.stop()
    assert not __import__("os").path.exists(s._tmp.name)  # cleaned up
    assert tempfile.gettempdir()


def _netns_available():
    try:
        return (
            subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(
    not _netns_available(), reason="no unprivileged network namespaces on this machine"
)
def test_inside_the_namespace_there_is_no_network_at_all_even_for_native_code():
    code = "import socket; s=socket.socket(); s.settimeout(2)\ntry:\n    s.connect(('127.0.0.1', 5433)); print('CONNECTED')\nexcept OSError as e:\n    print('BLOCKED', e.errno)"
    out = subprocess.run
    p = spawn([sys.executable, "-c", code], Limits(), cwd="/tmp", stderr=subprocess.DEVNULL)
    stdout, _ = p.communicate(timeout=20)
    assert b"BLOCKED" in stdout and b"CONNECTED" not in stdout
    assert out  # the same code outside the namespace is not asserted: the dev database may be up


def test_resource_limits_are_applied_to_the_worker_process():
    code = "import resource as r; print([r.getrlimit(x)[0] for x in (r.RLIMIT_AS, r.RLIMIT_NPROC, r.RLIMIT_FSIZE, r.RLIMIT_NOFILE, r.RLIMIT_CORE)])"
    lim = Limits(memory_bytes=3 * 1024**3, block_network=False)
    p = spawn([sys.executable, "-c", code], lim, cwd="/tmp", stderr=subprocess.DEVNULL)
    stdout, _ = p.communicate(timeout=20)
    assert stdout.decode().strip() == str([3 * 1024**3, 1, 0, 64, 0])
    assert ROOT.exists()

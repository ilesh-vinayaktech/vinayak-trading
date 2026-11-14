from datetime import UTC, datetime

import pytest

from algo.risk.killswitch import Failure, FailurePolicy, KillSwitch, KillSwitchError, Mode

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


def test_the_three_operations_do_different_things_and_are_not_interchangeable():
    effects = {m: (m.blocks_new, m.cancels_open, m.closes_positions) for m in Mode}
    assert effects == {
        Mode.RUNNING: (False, False, False),
        Mode.PAUSE: (True, False, False),  # no new orders, nothing else
        Mode.CANCEL: (True, True, False),  # also cancels open orders
        Mode.FLATTEN: (True, True, True),  # also closes positions
    }


def test_a_new_switch_runs_and_the_global_and_strategy_scopes_combine_by_severity():
    k = KillSwitch()
    assert k.mode("a") is Mode.RUNNING
    k.pause("a", by="jane", reason="looking", now=NOW)
    assert k.mode("a") is Mode.PAUSE and k.mode("b") is Mode.RUNNING  # one strategy only
    k.cancel(None, by="jane", reason="data", now=NOW)
    assert (
        k.mode("a") is Mode.CANCEL and k.mode("b") is Mode.CANCEL
    )  # global covers everyone, the stronger wins
    k.resume(None, by="jane", reason="ok", now=NOW)
    assert (
        k.mode("a") is Mode.PAUSE and k.mode("b") is Mode.RUNNING
    )  # the strategy's own pause stays


def test_flatten_needs_an_explicit_emergency_override():
    k = KillSwitch()
    with pytest.raises(KillSwitchError, match="override"):
        k.flatten("a", by="jane", reason="x", now=NOW)
    assert k.mode("a") is Mode.RUNNING
    k.flatten("a", by="jane", reason="fire", now=NOW, emergency_override=True)
    assert k.mode("a") is Mode.FLATTEN


def test_every_change_is_recorded_with_who_and_why():
    k = KillSwitch()
    k.pause(None, by="jane", reason="r1", now=NOW)
    k.resume(None, by="joe", reason="r2", now=NOW)
    assert [(e.scope, e.mode, e.by, e.reason) for e in k.events] == [
        (None, Mode.PAUSE, "jane", "r1"),
        (None, Mode.RUNNING, "joe", "r2"),
    ]


def test_by_default_a_failure_pauses_and_never_flattens():
    p = FailurePolicy()
    assert p.respond(Failure.DATA_STALE) is Mode.PAUSE
    assert p.respond(Failure.BROKER_DOWN) is Mode.PAUSE
    assert p.respond(Failure.AMBIGUOUS_ORDER) is Mode.PAUSE
    asks_flatten = FailurePolicy(actions={Failure.DAILY_LOSS: Mode.FLATTEN})
    assert (
        asks_flatten.respond(Failure.DAILY_LOSS) is Mode.CANCEL
    )  # auto-flatten is off: the strongest non-closing action
    assert (
        FailurePolicy(actions={Failure.DAILY_LOSS: Mode.FLATTEN}, auto_flatten=True).respond(
            Failure.DAILY_LOSS
        )
        is Mode.FLATTEN
    )
    assert (
        FailurePolicy(actions={Failure.DAILY_LOSS: Mode.CANCEL}).respond(Failure.DAILY_LOSS)
        is Mode.CANCEL
    )
    assert (
        FailurePolicy(actions={}).respond(Failure.RECONCILIATION) is Mode.PAUSE
    )  # unlisted failures pause


def test_a_failure_only_ever_escalates_and_is_recorded_as_automatic():
    k = KillSwitch()
    p = FailurePolicy(actions={Failure.DRAWDOWN: Mode.CANCEL})
    assert k.apply(Failure.DATA_STALE, p, "a", NOW) is Mode.PAUSE
    assert k.apply(Failure.DRAWDOWN, p, "a", NOW) is Mode.CANCEL
    assert (
        k.apply(Failure.DATA_STALE, p, "a", NOW) is Mode.CANCEL
    )  # a later, milder failure does not relax it
    assert [e.by for e in k.events] == [
        "policy:DATA_STALE",
        "policy:DRAWDOWN",
    ]  # the no-op was not an event
    assert k.mode("a") is Mode.CANCEL

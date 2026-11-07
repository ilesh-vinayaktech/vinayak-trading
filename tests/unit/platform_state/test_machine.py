from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algo.platform_state.machine import (
    ALLOWED,
    Checks,
    PlatformState,
    State,
    StateEvent,
    TransitionError,
)

T = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
GOOD = Checks(True, True, True, True, True, True)
FIELDS = list(Checks.__dataclass_fields__)


def at(state: State, live: bool = True) -> PlatformState:
    p = PlatformState(live_enabled=live)
    p.state = state
    return p


@pytest.mark.parametrize("src", list(State))
@pytest.mark.parametrize("dst", list(State))
def test_transition_matrix(src: State, dst: State) -> None:
    p = at(src)
    if dst in ALLOWED[src]:
        p.transition(dst, T, "t", checks=GOOD, operator=True)
        assert p.state is dst and p.events[-1].from_state is src
    else:
        with pytest.raises(TransitionError):
            p.transition(dst, T, "t", checks=GOOD, operator=True)
        assert p.state is src and not p.events


def test_boots_not_trading() -> None:
    assert not PlatformState().can_emit_targets()


@pytest.mark.parametrize("missing", FIELDS)
def test_ready_requires_each_check(missing: str) -> None:
    bad = Checks(**{n: n != missing for n in FIELDS})
    with pytest.raises(TransitionError, match="^recovery checks not satisfied$"):
        at(State.RECOVERY).transition(State.READY, T, "r", checks=bad)


def test_ready_without_checks_or_with_good_checks() -> None:
    with pytest.raises(TransitionError):
        at(State.RECOVERY).transition(State.READY, T, "r")
    p = at(State.RECOVERY)
    p.transition(State.READY, T, "r", checks=GOOD)
    assert p.state is State.READY


def test_ready_from_trading_state_needs_no_checks() -> None:
    p = at(State.PAPER)
    p.transition(State.READY, T, "pause")
    assert p.state is State.READY


def test_live_needs_flag() -> None:
    with pytest.raises(TransitionError, match="^live not enabled$"):
        at(State.READY, live=False).transition(State.LIVE, T, "go")
    p = at(State.READY, live=True)
    p.transition(State.LIVE, T, "go")
    assert p.can_emit_targets()


def test_halted_needs_operator() -> None:
    p = at(State.HALTED)
    with pytest.raises(TransitionError, match="^leaving HALTED requires operator action$"):
        p.transition(State.RECOVERY, T, "auto")
    p.transition(State.RECOVERY, T, "ops", operator=True)
    assert p.state is State.RECOVERY


def test_naive_ts_rejected() -> None:
    with pytest.raises(ValueError):
        PlatformState().transition(State.DATA_VALIDATION, datetime(2026, 1, 5), "x")  # noqa: DTZ001


def test_degraded_cannot_trade_or_resume_directly() -> None:
    assert not at(State.DEGRADED).can_emit_targets()
    for dst in (State.PAPER, State.LIVE, State.READY):
        with pytest.raises(TransitionError):
            at(State.DEGRADED).transition(dst, T, "x", checks=GOOD, operator=True)


@given(st.lists(st.sampled_from(list(State)), max_size=40), st.booleans())
def test_trading_only_entered_from_ready(path: list[State], ops: bool) -> None:
    """Property: any random walk entering PAPER/LIVE does so directly from READY."""
    p = PlatformState(live_enabled=True)
    for dst in path:
        try:
            p.transition(dst, T, "w", checks=GOOD, operator=ops)
        except TransitionError:
            continue
        if p.state in {State.PAPER, State.LIVE}:
            assert p.events[-1].from_state is State.READY


def test_the_recorded_event_carries_the_exact_time_states_and_reason():
    p = at(State.READY)
    p.transition(State.PAPER, T, "operator started paper trading")
    assert p.events == [StateEvent(T, State.READY, State.PAPER, "operator started paper trading")]


def test_event_time_is_normalised_to_utc():
    from datetime import timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    p = at(State.READY)
    p.transition(State.PAPER, datetime(2026, 1, 5, 9, 30, tzinfo=ist), "x")
    assert p.events[0].ts.utcoffset() == timedelta(0) and p.events[0].ts == datetime(
        2026, 1, 5, 4, 0, tzinfo=UTC
    )


def test_live_is_off_by_default():
    p = PlatformState()  # default constructor: live trading not enabled
    p.state = State.READY
    with pytest.raises(TransitionError, match="^live not enabled$"):
        p.transition(State.LIVE, T, "go")


def test_illegal_transition_message_names_both_states():
    with pytest.raises(TransitionError, match="^HALTED -> PAPER not allowed$"):
        at(State.HALTED).transition(State.PAPER, T, "x", operator=True)

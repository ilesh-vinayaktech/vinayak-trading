import pytest

from algo.execution.live_gate import LiveGate, LiveRefused, mode, open_gate, problems

ON = {"ALGO_LIVE": "1"}


def test_live_needs_the_explicit_flag_a_live_stage_strategy_and_a_valid_session():
    assert problems(ON, "LIVE", True) == []
    assert "ALGO_LIVE" in problems({}, "LIVE", True)[0]
    assert (
        problems({"ALGO_LIVE": "0"}, "LIVE", True) != []
        and problems({"ALGO_LIVE": "true"}, "LIVE", True) != []
    )  # only "1" counts
    assert "LIVE stage" in problems(ON, "PAPER", True)[0] and problems(ON, "RESEARCH", True) != []
    assert "session" in problems(ON, "LIVE", False)[0]


def test_every_missing_condition_is_reported_not_just_the_first():
    assert len(problems({}, "PAPER", False)) == 3


def test_anything_that_is_not_fully_live_is_paper():
    assert mode(ON, "LIVE", True) == "LIVE"
    assert (
        mode(ON, "LIVE", False) == "PAPER"
        and mode({}, "LIVE", True) == "PAPER"
        and mode(ON, "PAPER", True) == "PAPER"
    )


def test_a_gate_opens_only_when_nothing_is_missing_and_refuses_with_every_reason():
    gate = open_gate(ON, "LIVE", True)
    assert isinstance(gate, LiveGate) and gate.open
    with pytest.raises(LiveRefused, match="ALGO_LIVE.*LIVE stage.*session"):
        open_gate({}, "PAPER", False)
    assert not LiveGate(open=False).open  # a closed gate is not a pass

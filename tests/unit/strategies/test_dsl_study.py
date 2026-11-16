# ruff: noqa: E501
"""A registered strategy definition run through the study machinery: the grid varies only its numeric knobs, the definition itself is locked in the study."""

import pytest
from pydantic import ValidationError

from algo.factory import generate
from algo.research.study import StudyError, check
from algo.research.study_runner import build
from algo.strategies.dsl_study import DslParams, DslStudyStrategy, apply
from tests.unit.research.test_study import TODAY, spec

DEFN = generate.definition_for(
    generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
)


def dsl_spec(**over):
    base = {
        "strategy_id": "dsl",
        "definition": DEFN.canonical(),
        "grid": {"entry_share": [10, 20], "max_positions": [10, 20]},
        "universe": {"segments": ["large"], "min_history_sessions": 252},
    }
    return spec(**{**base, **over})


def test_no_override_leaves_the_definition_exactly_as_written():
    assert apply(DEFN, DslParams()).sha256 == DEFN.sha256


def test_the_knobs_change_only_the_numbers_they_name():
    d = apply(DEFN, DslParams(entry_share=10, exit_share=40, max_positions=5))
    assert d.entry.conditions()[0].value == 10 and d.exit.conditions()[0].value == 40
    assert d.position.max_positions == 5
    assert (d.entry.conditions()[0].op, d.ranking, d.rebalance) == (
        "TOP_PERCENT",
        DEFN.ranking,
        DEFN.rebalance,
    )
    assert d.sha256 != DEFN.sha256


def test_a_knob_that_does_not_apply_is_refused_not_ignored():
    plain = DEFN.model_copy(deep=True)
    raw = plain.canonical()
    raw["entry"] = {"all": [{"feature": "ret_20d", "op": ">", "value": 0}]}
    from algo.factory.dsl import StrategyDef

    with pytest.raises(ValueError, match="entry_share"):
        apply(StrategyDef.model_validate(raw), DslParams(entry_share=10))


def test_shares_must_be_a_real_percentage():
    for bad in (0, 101):
        with pytest.raises(ValidationError):
            DslParams(entry_share=bad)


def test_a_sound_dsl_study_passes_and_the_strategy_id_and_definition_go_together():
    s = dsl_spec()
    check(s, today=TODAY)
    assert len(s.grid) == 2
    with pytest.raises(StudyError, match="definition"):
        check(dsl_spec(definition=None), today=TODAY)
    with pytest.raises(StudyError, match="definition"):
        check(spec(definition=DEFN.canonical()), today=TODAY)


def test_build_runs_the_locked_definition_with_the_combination_applied():
    s = dsl_spec()

    class Setup:
        membership = object()

    st = build(s, {"entry_share": 10, "max_positions": 5}, Setup())
    assert isinstance(st, DslStudyStrategy)
    assert st.inner.defn.position.max_positions == 5
    assert st.inner.defn.entry.conditions()[0].value == 10

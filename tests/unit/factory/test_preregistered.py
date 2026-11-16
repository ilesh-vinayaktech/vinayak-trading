# ruff: noqa: E501
"""The three return-oriented strategies written down BEFORE any result (review 2026-11-16, section 3.7): plain momentum, momentum among the calmer stocks, and momentum with a market filter."""

import pytest

from algo.factory import preregistered
from algo.factory.dsl import MARKET_BREADTH


def test_every_preregistered_definition_is_valid_monthly_long_only_and_reads_twelve_month_momentum():
    defs = preregistered.definitions()
    assert [d.strategy_id for d in defs] == [
        "MOMENTUM_12M_M",
        "MOMENTUM_LOWVOL_M",
        "MOMENTUM_TREND_M",
    ]
    for d in defs:
        assert (
            d.rebalance == "MONTHLY"
            and d.position.max_positions == 15
            and d.ranking.feature == "ret_252d"
        )
        assert (
            d.entry.conditions()[0].feature == "ret_252d"
            and d.entry.conditions()[0].op == "TOP_PERCENT"
        )
        assert len(d.description) <= 500 and "review 2026-11-16" in d.description


def test_the_second_adds_a_calm_filter_and_the_third_a_market_filter_and_only_those():
    plain, calm, trend = preregistered.definitions()
    assert [c.feature for c in plain.entry.conditions()] == ["ret_252d"]
    assert [(c.feature, c.op) for c in calm.entry.conditions()] == [
        ("ret_252d", "TOP_PERCENT"),
        ("vol_60d", "BOTTOM_PERCENT"),
    ]
    assert [(c.feature, c.op, int(c.value)) for c in trend.entry.conditions()] == [
        ("ret_252d", "TOP_PERCENT", 20),
        (MARKET_BREADTH, ">=", 50),
    ]
    assert (MARKET_BREADTH, "<", 40) in [
        (c.feature, c.op, int(c.value)) for c in trend.exit.conditions()
    ]  # a weak market sells what is held


def test_the_numbers_are_the_documented_priors_not_tuned_values():
    assert (
        preregistered.ENTRY_SHARE,
        preregistered.EXIT_SHARE,
        preregistered.CALM_SHARE,
        preregistered.POSITIONS,
    ) == (20, 50, 67, 15)
    assert (preregistered.MARKET_IN, preregistered.MARKET_OUT) == (50, 40)


def test_a_market_filter_definition_is_not_drawn_on_the_chart_and_says_why():
    from algo.factory import signals

    trend = preregistered.definitions()[2]
    with pytest.raises(signals.SignalsError, match="market"):
        signals.features_used(trend)

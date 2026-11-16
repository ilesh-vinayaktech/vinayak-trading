# ruff: noqa: E501
"""From a CANDIDATE alpha hypothesis to a strategy definition: fixed priors only, nothing fitted to the development data."""

import pytest

from algo.factory import generate


def hyp(feature="ret_20d", horizon=20, direction="POSITIVE", hid=7, ic=0.04, p=0.003, batch=1):
    return generate.Hypothesis(hid, batch, feature, "1", horizon, direction, ic, p)


def test_a_positive_signal_buys_the_strongest_fifth_and_sells_when_the_stock_falls_into_the_weak_half():
    d = generate.definition_for(hyp())
    assert (d.strategy_id, d.version, d.universe, d.timeframe) == (
        "ALPHA_RET_20D_H20",
        1,
        "MEMBERS",
        "DAILY",
    )
    (entry,) = d.entry.conditions()
    (exit_,) = d.exit.conditions()
    assert (entry.feature, entry.op, entry.value) == (
        "ret_20d",
        "TOP_PERCENT",
        20,
    ) and d.entry.mode() == "all"
    assert (exit_.feature, exit_.op, exit_.value) == (
        "ret_20d",
        "BOTTOM_PERCENT",
        50,
    ) and d.exit.mode() == "any"
    assert (d.ranking.feature, d.ranking.order) == ("ret_20d", "DESC")
    assert (d.position.max_positions, d.position.sizing, d.risk.max_position_percent) == (
        20,
        "EQUAL_WEIGHT",
        10,
    )
    assert d.rebalance == "MONTHLY"


def test_a_negative_signal_buys_the_weakest_fifth_and_ranks_ascending():
    d = generate.definition_for(hyp(feature="vol_20d", horizon=5, direction="NEGATIVE"))
    assert d.strategy_id == "ALPHA_VOL_20D_H5" and d.rebalance == "WEEKLY"
    assert (d.entry.conditions()[0].op, d.exit.conditions()[0].op, d.ranking.order) == (
        "BOTTOM_PERCENT",
        "TOP_PERCENT",
        "ASC",
    )


def test_the_rebalance_follows_the_horizon_the_signal_was_measured_at():
    assert [generate.definition_for(hyp(horizon=h)).rebalance for h in (1, 5, 20, 60)] == [
        "DAILY",
        "WEEKLY",
        "MONTHLY",
        "MONTHLY",
    ]


def test_the_description_traces_the_definition_back_to_its_evidence_and_the_rules_do_not_depend_on_which_hypothesis_made_them():
    d = generate.definition_for(hyp(hid=42, ic=0.0431, p=0.0012, batch=3))
    assert (
        "hypothesis 42" in d.description
        and "batch 3" in d.description
        and "0.0431" in d.description
        and "20 days" in d.description
        and len(d.description) <= 500
    )
    a, b = generate.definition_for(hyp(hid=1)), generate.definition_for(hyp(hid=2))
    assert a.description != b.description
    assert {k: v for k, v in a.canonical().items() if k != "description"} == {
        k: v for k, v in b.canonical().items() if k != "description"
    }


def test_a_candidate_the_language_cannot_express_is_refused_with_the_reason_not_approximated():
    with pytest.raises(generate.NotExpressible, match="no direction"):
        generate.definition_for(hyp(direction=None))
    with pytest.raises(generate.NotExpressible, match="atr_14d.*all of its history"):
        generate.definition_for(hyp(feature="atr_14d"))
    with pytest.raises(generate.NotExpressible, match="rsi_14d.*all of its history"):
        generate.definition_for(hyp(feature="rsi_14d"))
    with pytest.raises(generate.NotExpressible, match="fund_roe.*filings"):
        generate.definition_for(hyp(feature="fund_roe"))
    with pytest.raises(generate.NotExpressible, match="not_a_feature.*not a feature"):
        generate.definition_for(hyp(feature="not_a_feature"))


def test_the_priors_are_the_documented_constants():
    assert (
        generate.ENTRY_SHARE,
        generate.EXIT_SHARE,
        generate.MAX_POSITIONS,
        generate.MAX_POSITION_PERCENT,
    ) == (20, 50, 20, 10)

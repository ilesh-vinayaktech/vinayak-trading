# ruff: noqa: E501
"""A strategy definition in plain words: what it buys, when it sells, how much it holds, without feature names or operators."""

from algo.factory import generate, plain, preregistered
from algo.factory.dsl import StrategyDef


def hyp(feature, horizon, direction):
    return generate.definition_for(
        generate.Hypothesis(1, 1, feature, "1", horizon, direction, 0.05, 0.001)
    )


def test_a_momentum_rule_reads_as_a_sentence_a_person_would_say():
    p = plain.describe(hyp("ret_252d", 20, "POSITIVE"))
    assert p["when"] == "Once a month"
    assert (
        p["buy"]
        == "Buy a stock when it is among the 20% of stocks with the highest price change over the last 12 months."
    )
    assert (
        p["sell"]
        == "Sell it when it falls into the 50% of stocks with the lowest price change over the last 12 months."
    )
    assert (
        p["size"]
        == "Hold at most 20 stocks, each the same size (never more than 10% of the money in one)."
    )
    assert (
        p["summary"]
        == "Once a month: buy the 20% of stocks with the highest price change over the last 12 months; sell when one falls into the 50% with the lowest."
    )


def test_a_calm_stock_rule_reads_the_other_way_round():
    p = plain.describe(hyp("vol_20d", 5, "NEGATIVE"))
    assert p["when"] == "Once a week"
    assert (
        "among the 20% of stocks with the lowest price swings over the last month (volatility)"
        in p["buy"]
    )
    assert (
        "falls into the 50% of stocks with the highest price swings" in p["sell"]
        or "moves into the 50% of stocks with the highest price swings" in p["sell"]
    )


def test_two_conditions_say_all_or_any_and_a_market_filter_says_what_the_market_must_look_like():
    plain_def, calm, trend = preregistered.definitions()
    assert plain.describe(calm)["summary"].startswith(
        "Once a month: buy a stock when it is among the 20% of stocks with the highest price change"
    )  # two conditions: the summary is the buy rule itself
    b = plain.describe(calm)["buy"]
    assert (
        "and" in b
        and "highest price change over the last 12 months" in b
        and "lowest price swings over the last 3 months" in b
    )
    t = plain.describe(trend)
    assert "at least 50% of all stocks are above their 200-day average" in t["buy"]
    assert (
        "Sell everything when fewer than 40% of all stocks are above their 200-day average"
        in t["sell"]
        or "fewer than 40% of all stocks are above their 200-day average" in t["sell"]
    )
    assert (
        "any one of these" not in plain.describe(plain_def)["sell"]
    )  # a single condition needs no 'any'


def test_a_threshold_condition_and_an_unknown_feature_still_read_sensibly():
    raw = hyp("ret_20d", 1, "POSITIVE").canonical()
    raw["entry"] = {"all": [{"feature": "ret_20d", "op": ">", "value": 0}]}
    raw["rebalance"] = "DAILY"
    assert (
        "price change over the last month is above 0"
        in plain.describe(StrategyDef.model_validate(raw))["buy"]
    )
    assert plain.describe(StrategyDef.model_validate(raw))["when"] == "Every trading day"
    assert (
        plain.phrase("some_new_feature") == "some new feature"
    )  # a feature with no wording yet: its name, spaced, never a crash

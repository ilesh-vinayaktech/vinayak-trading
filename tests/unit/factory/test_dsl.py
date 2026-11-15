import json

import pytest
from pydantic import ValidationError

from algo.factory import dsl

BASE = {
    "strategy_id": "MOM_001",
    "version": 1,
    "description": "Buy stocks that are up over three months and above their 50-day average; sell when they fall below it.",
    "universe": "MEMBERS",
    "timeframe": "DAILY",
    "entry": {
        "all": [
            {"feature": "ret_60d", "op": ">", "value": 0.05},
            {"feature": "dist_sma_50d", "op": ">", "value": 0},
        ]
    },
    "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": 0}]},
    "ranking": {"feature": "ret_60d", "order": "DESC"},
    "position": {"max_positions": 10, "sizing": "EQUAL_WEIGHT"},
    "risk": {"max_position_percent": 10},
    "rebalance": "WEEKLY",
}


def make(**over):
    return dsl.StrategyDef.model_validate({**BASE, **over})


def test_a_well_formed_definition_parses_and_exposes_what_it_needs():
    d = make()
    assert (d.strategy_id, d.version, d.rebalance) == ("MOM_001", 1, "WEEKLY")
    assert d.required_features() == {"ret_60d", "dist_sma_50d"}
    assert d.warmup_bars() == 61  # ret_60d needs 61 bars, dist_sma_50d 50: the longest decides


def test_the_warmup_is_the_longest_of_the_features_it_uses_and_inverse_volatility_adds_its_own():
    assert (
        make(entry={"all": [{"feature": "ret_252d", "op": ">", "value": 0}]}).warmup_bars() == 253
    )
    d = make(position={"max_positions": 5, "sizing": "INVERSE_VOLATILITY"})
    assert "vol_20d" in d.required_features() and d.warmup_bars() == 61


def test_the_hash_is_the_same_whatever_the_key_order_or_number_spelling_and_changes_with_any_rule():
    a = make()
    reordered = dsl.StrategyDef.model_validate(
        json.loads(json.dumps(dict(reversed(list(BASE.items())))))
    )
    spelled = make(
        entry={
            "all": [
                {"feature": "ret_60d", "op": ">", "value": "0.050"},
                {"feature": "dist_sma_50d", "op": ">", "value": 0.0},
            ]
        }
    )
    assert a.sha256 == reordered.sha256 == spelled.sha256 and len(a.sha256) == 64
    for change in (
        {"version": 2},
        {"rebalance": "MONTHLY"},
        {"risk": {"max_position_percent": 12}},
        {"ranking": {"feature": "ret_20d", "order": "DESC"}},
        {"entry": {"all": [{"feature": "ret_60d", "op": ">=", "value": 0.05}]}},
        {"position": {"max_positions": 11, "sizing": "EQUAL_WEIGHT"}},
    ):
        assert make(**change).sha256 != a.sha256, change


def test_an_unknown_feature_is_refused_naming_it_and_the_ones_that_exist():
    with pytest.raises(ValidationError) as e:
        make(entry={"all": [{"feature": "magic_alpha", "op": ">", "value": 1}]})
    text = str(e.value)
    assert "magic_alpha" in text and "ret_60d" in text


@pytest.mark.parametrize(
    "bad",
    [
        {"entry": {"all": [], "any": []}},  # nothing to decide on
        {
            "entry": {
                "all": [{"feature": "ret_60d", "op": ">", "value": 0}],
                "any": [{"feature": "ret_20d", "op": ">", "value": 0}],
            }
        },  # both groups
        {"entry": {}},
        {"exit": {"any": []}},
        {"entry": {"all": [{"feature": "ret_60d", "op": "~", "value": 0}]}},  # unknown operator
        {"entry": {"all": [{"feature": "ret_60d", "op": ">", "value": "high"}]}},  # not a number
        {
            "entry": {"all": [{"feature": "ret_60d", "op": ">", "value": True}]}
        },  # a boolean is not a threshold
        {"entry": {"all": [{"feature": "ret_60d", "op": ">", "value": float("nan")}]}},
        {"position": {"max_positions": 0, "sizing": "EQUAL_WEIGHT"}},
        {"position": {"max_positions": 51, "sizing": "EQUAL_WEIGHT"}},
        {"position": {"max_positions": 5, "sizing": "KELLY"}},
        {"risk": {"max_position_percent": 0}},
        {"risk": {"max_position_percent": 101}},
        {"version": 0},
        {"strategy_id": "lower case"},
        {"strategy_id": "AB"},
        {"universe": "ALL_STOCKS"},
        {"timeframe": "1M"},
        {"rebalance": "HOURLY"},
        {"description": ""},
        {"unexpected": 1},
    ],
)
def test_malformed_definitions_are_refused(bad):
    with pytest.raises(ValidationError):
        make(**bad)


def test_the_equal_share_and_the_cap_are_stated_so_a_binding_cap_is_visible():
    d = make(
        position={"max_positions": 4, "sizing": "EQUAL_WEIGHT"}, risk={"max_position_percent": 10}
    )
    assert (
        d.position_cap() == 0.10 and d.equal_share() == 0.25
    )  # the cap binds: each position is held at 10%, the rest is cash


def test_parse_reads_json_text_and_refuses_text_that_is_not_one_object():
    assert dsl.parse(json.dumps(BASE)).sha256 == make().sha256
    for bad in ("not json", "[1, 2]", ""):
        with pytest.raises(ValueError):
            dsl.parse(bad)


def test_a_definition_is_immutable():
    d = make()
    with pytest.raises((ValidationError, TypeError)):
        d.version = 2


def test_a_feature_whose_value_depends_on_all_history_cannot_be_used_yet_and_a_nan_text_is_not_a_threshold():
    for chained in ("atr_14d", "atr_pct_14d", "rsi_14d"):
        with pytest.raises(ValidationError, match=chained):
            make(entry={"all": [{"feature": chained, "op": ">", "value": 1}]})
    with pytest.raises(ValidationError):
        make(entry={"all": [{"feature": "ret_60d", "op": ">", "value": "NaN"}]})
    with pytest.raises(ValidationError):
        make(entry={"all": [{"feature": "ret_60d", "op": ">", "value": "Infinity"}]})


def test_the_group_says_which_mode_it_is_and_lists_its_conditions_in_order():
    d = make()
    assert d.entry.mode() == "all" and d.exit.mode() == "any"
    assert [c.feature for c in d.entry.conditions()] == ["ret_60d", "dist_sma_50d"]


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_the_canonical_form_is_exact_plain_text_with_numbers_as_strings_and_nothing_empty():
    assert make().canonical() == {
        "strategy_id": "MOM_001", "version": 1,
        "description": "Buy stocks that are up over three months and above their 50-day average; sell when they fall below it.",
        "universe": "MEMBERS", "timeframe": "DAILY",
        "entry": {"all": [{"feature": "ret_60d", "op": ">", "value": "0.05"}, {"feature": "dist_sma_50d", "op": ">", "value": "0"}]},
        "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": "0"}]},
        "ranking": {"feature": "ret_60d", "order": "DESC"},
        "position": {"max_positions": 10, "sizing": "EQUAL_WEIGHT"},
        "risk": {"max_position_percent": "10"},
        "rebalance": "WEEKLY",
    }  # fmt: skip


def test_a_threshold_of_one_stays_one_and_zero_has_one_spelling():
    one = make(entry={"all": [{"feature": "ret_60d", "op": ">", "value": 1}]}).canonical()["entry"][
        "all"
    ][0]["value"]
    assert one == "1"
    zeros = {
        make(entry={"all": [{"feature": "ret_60d", "op": ">", "value": v}]}).sha256
        for v in (0, 0.0, "0.000", "-0")
    }
    assert len(zeros) == 1


def test_each_refusal_says_exactly_what_is_wrong_with_the_number_or_the_text():
    def why(**over):
        with pytest.raises(ValidationError) as e:
            make(**over)
        return str(e.value)

    cond = lambda v: {"entry": {"all": [{"feature": "ret_60d", "op": ">", "value": v}]}}  # noqa: E731
    assert "Value error, a boolean is not a number" in why(**cond(True))
    assert "Value error, a threshold must be a finite number" in why(**cond(float("nan")))
    assert "Value error, a threshold must be a finite number" in why(**cond(float("inf")))
    assert "Value error, a threshold must be a finite number" in why(**cond("Infinity"))
    assert "Value error, 'high' is not a number" in why(**cond("high"))


def test_parse_says_what_shape_it_wants():
    with pytest.raises(ValueError) as e:
        dsl.parse("[1, 2]")
    assert str(e.value) == "a strategy definition is one JSON object"


def test_a_fundamental_feature_cannot_be_used_in_a_definition_yet_because_the_interpreter_has_no_filings():
    with pytest.raises(ValidationError, match="fund_roe"):
        make(entry={"all": [{"feature": "fund_roe", "op": ">", "value": 10}]})
    with pytest.raises(ValidationError, match="unknown feature"):
        make(ranking={"feature": "fund_revenue_growth", "order": "DESC"})
    assert make(
        entry={"all": [{"feature": "ret_1d", "op": ">", "value": 0}]}
    )  # the new price features are usable

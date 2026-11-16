"""A backtest study's settings: everything the owner configures, checked before it can be registered (and locked)."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.research.study import (
    MAX_TRIALS,
    SURVIVORSHIP_SAFE_FROM,
    StudyError,
    StudySpec,
    check,
    combinations,
    default_thresholds,
)

TODAY = date(2026, 11, 12)


def spec(**over) -> StudySpec:
    base = {
        "name": "Pullback, large and mid caps",
        "hypothesis": "Buying a 5-day RSI dip inside a 200-day uptrend beats buy-and-hold after costs.",
        "strategy_id": "trend_pullback",
        "grid": {
            "trend_sma": [100, 200],
            "entry_rsi": [20, 25, 30],
            "exit_rsi": [60, 65],
            "max_positions": [10],
        },
        "universe": {"segments": ["large", "mid"]},
        "start": "2019-10-01",
        "end": "2026-11-06",
        "holdout_start": "2024-05-01",
        "capital": "1000000",
        "broker": "zerodha",
        "thresholds": default_thresholds(),
        "family_id": 1,  # the family every migrated database starts with
    }
    return StudySpec.model_validate({**base, **over})


def test_a_sound_study_passes_and_its_grid_is_every_combination_in_a_fixed_order():
    s = spec()
    check(s, today=TODAY)
    combos = combinations(s)
    assert len(combos) == 12
    assert combos[0] == {"entry_rsi": 20, "exit_rsi": 60, "max_positions": 10, "trend_sma": 100}
    assert combos == combinations(spec())  # deterministic


def test_the_defaults_are_daily_bars_three_times_capital_for_capacity_and_a_year_of_history_per_stock():
    s = spec()
    assert (s.timeframe, s.capacity_multiple, s.universe.min_history_sessions, s.universe.before_segment_lists) == (
        "1D", D(3), 252, "traded_value_rank",
    )  # fmt: skip


def test_the_thresholds_start_as_the_provisional_ones_and_all_twelve_are_required():
    t = default_thresholds()
    assert len(t) == 12 and t["owner_max_drawdown"] == "1.0" and t["min_oos_sharpe"] == "0.8"
    with pytest.raises(StudyError, match="thresholds"):
        check(spec(thresholds={k: v for k, v in t.items() if k != "max_pbo"}), today=TODAY)


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"strategy_id": "nope"}, "unknown strategy"),
        ({"grid": {"lookback": [5]}}, "trend_pullback has no parameter 'lookback'"),
        ({"grid": {"entry_rsi": [99]}}, "entry_rsi=99 is not allowed"),
        ({"grid": {"entry_rsi": [20, 20]}}, "repeats"),
        ({"grid": {}}, "at least one parameter"),
        ({"grid": {"entry_rsi": []}}, "at least one value"),
        ({"holdout_start": "2019-09-01"}, "holdout must start after the study starts"),
        ({"holdout_start": "2026-11-07"}, "holdout must start on or before the study's end"),
        ({"end": "2027-01-01", "holdout_start": "2024-05-01"}, "in the future"),
        ({"holdout_start": "2026-10-01"}, "holdout is 1%"),
        ({"holdout_start": "2020-01-01"}, "holdout is 96%"),
        ({"start": "2016-01-01"}, "survivorship"),
    ],
)
def test_settings_that_cannot_be_honoured_are_refused_with_the_reason(over, why):
    with pytest.raises(StudyError, match=why):
        check(spec(**over), today=TODAY)


def test_an_early_start_is_allowed_once_the_survivorship_bias_is_accepted_explicitly():
    check(spec(start="2016-01-01", accept_survivorship_bias=True), today=TODAY)
    assert SURVIVORSHIP_SAFE_FROM == date(2019, 10, 1)


def test_a_grid_too_large_is_refused_because_every_combination_counts_against_the_strategy():
    big = {
        "trend_sma": [100, 200],
        "entry_rsi": [20, 25, 30],
        "exit_rsi": [55, 60, 65],
        "max_positions": [5, 10, 20],
    }
    assert 2 * 3 * 3 * 3 <= MAX_TRIALS  # the whole grid of this strategy is allowed ...
    check(spec(grid=big), today=TODAY)
    with pytest.raises(StudyError, match="trials"):
        check(spec(grid=big), today=TODAY, max_trials=10)  # ... a smaller cap refuses it


def test_unknown_settings_and_impossible_values_are_refused_before_anything_else():
    with pytest.raises(ValueError):
        spec(colour="blue")
    with pytest.raises(ValueError):
        spec(capital="-5")
    with pytest.raises(ValueError):
        spec(universe={"segments": []})
    with pytest.raises(ValueError):
        spec(timeframe="5m")  # only daily bars until the engine runs intraday strategies


def test_slippage_is_a_setting_with_a_realistic_default_and_can_be_changed_or_refused():
    s = spec()
    assert (
        s.slippage.base_bps,
        s.slippage.participation_bps_per_pct,
        s.slippage.volatility_fraction,
    ) == (D(5), D(5), D(0))
    custom = spec(
        slippage={"base_bps": "12", "participation_bps_per_pct": "2", "volatility_fraction": "0.1"}
    )
    assert custom.slippage.base_bps == D(12) and custom.slippage.volatility_fraction == D("0.1")
    with pytest.raises(ValueError):
        spec(slippage={"base_bps": "-1"})
    with pytest.raises(ValueError):
        spec(slippage={"base_bps": "5000"})  # beyond the model's own 1000 bps ceiling


def test_a_minimum_history_shorter_than_the_strategys_longest_lookback_is_refused():
    check(
        spec(universe={"segments": ["large"], "min_history_sessions": 210}), today=TODAY
    )  # 200-day average + warm-up
    with pytest.raises(StudyError, match="210 sessions"):
        check(spec(universe={"segments": ["large"], "min_history_sessions": 100}), today=TODAY)
    check(
        spec(
            grid={"trend_sma": [100], "entry_rsi": [25]},
            universe={"segments": ["large"], "min_history_sessions": 110},
        ),
        today=TODAY,
    )


def test_order_size_limits_are_off_by_default_and_must_make_sense():
    s = spec()
    assert s.min_order_value == D(0) and s.max_order_value is None
    custom = spec(min_order_value="5000", max_order_value="100000")
    assert (custom.min_order_value, custom.max_order_value) == (D(5000), D(100000))
    with pytest.raises(ValueError):
        spec(min_order_value="-1")
    with pytest.raises(ValueError):
        spec(max_order_value="0")
    with pytest.raises(ValueError, match="maximum"):
        spec(min_order_value="5000", max_order_value="1000")


SCREEN = {"conditions": [{"field": "rsi_14", "op": "lt", "value": 30}], "sort": "chg_6m"}


def test_a_screener_study_needs_a_price_only_screen_and_only_it_takes_one():
    ok = spec(strategy_id="screener", grid={"max_positions": [10]}, screen=SCREEN)
    check(ok, today=TODAY)
    assert combinations(ok) == [{"max_positions": 10}]
    with pytest.raises(StudyError, match="needs its screen"):
        check(spec(strategy_id="screener", grid={"max_positions": [10]}), today=TODAY)
    with pytest.raises(StudyError, match="needs its screen"):
        check(spec(screen=SCREEN), today=TODAY)  # a code strategy takes no screen
    check(
        spec(
            strategy_id="screener",
            grid={"max_positions": [10]},
            screen={"conditions": [{"field": "pe", "op": "lt", "value": 15}], "sort": "chg_6m"},
        ),
        today=TODAY,
    )  # filed ratios are fine in a study
    bad = {"conditions": [{"field": "segment", "op": "eq", "value": "large"}], "sort": "chg_6m"}
    with pytest.raises(StudyError, match="market-cap class"):
        check(spec(strategy_id="screener", grid={"max_positions": [10]}, screen=bad), today=TODAY)


def test_a_grid_that_leaves_a_parameter_out_uses_its_default_instead_of_crashing():
    check(
        spec(grid={"max_positions": [10]}), today=TODAY
    )  # trend_sma is not in the grid: its default (200) applies


def test_a_grid_without_the_trend_average_is_refused_with_a_reason_when_the_history_asked_for_is_too_short():
    short = {"segments": ["large", "mid"], "min_history_sessions": 100}
    with pytest.raises(
        StudyError, match="at least 210 sessions"
    ):  # the default 200-day average plus warm-up
        check(spec(grid={"max_positions": [10]}, universe=short), today=TODAY)


def test_a_study_may_not_reach_into_the_global_research_holdout():
    check(spec(), today=TODAY)  # no lock given: only the other rules apply
    late = spec(end="2025-01-02", holdout_start="2024-05-01")
    with pytest.raises(StudyError, match="inside the global research holdout"):
        check(late, today=TODAY, development_end=date(2024, 12, 31))
    ok = spec(end="2024-12-31", holdout_start="2024-05-01")
    check(
        ok, today=TODAY, development_end=date(2024, 12, 31)
    )  # the last development day itself is allowed


def test_the_filing_lag_defaults_to_zero_is_bounded_and_enters_the_locked_document():
    assert spec().filing_lag_days == 0
    assert spec(filing_lag_days=45).model_dump(mode="json")["filing_lag_days"] == 45
    for bad in (-1, 366):
        with pytest.raises(ValueError):
            spec(filing_lag_days=bad)


def test_the_per_trade_stop_and_cooldown_are_off_by_default_and_must_be_sensible():
    s = spec()
    assert (
        s.trade_stop is None and s.stop_cooldown_days == 0
    )  # studies registered before they existed ran without them
    on = spec(trade_stop="0.02", stop_cooldown_days=5)
    assert on.trade_stop == D("0.02") and on.stop_cooldown_days == 5
    for bad in (
        {"trade_stop": "0"},
        {"trade_stop": "1"},
        {"stop_cooldown_days": -1},
        {"stop_cooldown_days": 61},
    ):
        with pytest.raises(ValueError):
            spec(**bad)


def test_a_fixed_setting_must_be_one_of_the_combinations_and_is_off_by_default():
    assert spec().fixed is None
    ok = spec(fixed={"entry_rsi": 25, "exit_rsi": 60, "max_positions": 10, "trend_sma": 100})
    check(ok, today=TODAY)  # decided before the study, and inside its grid
    with pytest.raises(StudyError, match="fixed"):
        check(
            spec(fixed={"entry_rsi": 99, "exit_rsi": 60, "max_positions": 10, "trend_sma": 100}),
            today=TODAY,
        )
    with pytest.raises(StudyError, match="fixed"):
        check(spec(fixed={"entry_rsi": 25}), today=TODAY)  # every grid setting must be named

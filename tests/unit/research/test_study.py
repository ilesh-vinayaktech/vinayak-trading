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
    assert len(t) == 12 and t["owner_max_drawdown"] == "0.25" and t["min_oos_sharpe"] == "0.8"
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

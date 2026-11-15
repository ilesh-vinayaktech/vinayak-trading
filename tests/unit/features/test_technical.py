# ruff: noqa: E501
"""The second feature set (price and volume, version 1): each against numbers worked out by hand, then the rules every feature shares."""

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.features import price, technical
from algo.features._shared import SessionBar

DAYS = [date(2026, 1, 5) + timedelta(days=i) for i in range(8)]


def at(day, extra_hours=0):
    return datetime(day.year, day.month, day.day, 13, 0, tzinfo=UTC) + timedelta(hours=extra_hours)


def bar(day, close, high=None, low=None, raw_vol=1000, extra_hours=0):
    close = D(str(close))
    return SessionBar(
        day,
        D(str(high)) if high is not None else close,
        D(str(low)) if low is not None else close,
        close,
        close,
        D(raw_vol),
        at(day, extra_hours),
    )


def series(closes, **kw):
    return {d: bar(d, c, **kw) for d, c in zip(DAYS, closes, strict=False)}


# ---- RSI: Wilder's smoothing, first value from the first n changes ------------------------------------------------
def test_rsi_first_value_is_the_plain_mean_of_the_first_n_gains_and_losses():
    bars = series(
        [10, 11, 10, 12]
    )  # changes +1, -1, +2: average gain 3/3 = 1, average loss 1/3, RS = 3, RSI = 100 - 100/4
    r = technical.rsi(3)(DAYS[:4], bars)
    assert sorted(r) == [DAYS[3]] and r[DAYS[3]][0] == D("75")


def test_rsi_then_follows_wilders_recursion():
    bars = series(
        [10, 11, 10, 12, 11]
    )  # next change -1: gain (1*2+0)/3 = 2/3, loss (1/3*2+1)/3 = 5/9, RS = 6/5
    r = technical.rsi(3)(DAYS[:5], bars)
    assert r[DAYS[4]][0] == D("54.545454545455")  # 100 - 100 / (11/5)


def test_rsi_of_only_rises_is_100_of_a_flat_series_is_50_and_of_only_falls_is_0():
    assert technical.rsi(3)(DAYS[:4], series([10, 11, 12, 13]))[DAYS[3]][0] == D("100")
    assert technical.rsi(3)(DAYS[:4], series([10, 10, 10, 10]))[DAYS[3]][0] == D("50")
    assert technical.rsi(3)(DAYS[:4], series([13, 12, 11, 10]))[DAYS[3]][0] == D("0")


def test_rsi_restarts_after_a_missing_session():
    full = series([10, 11, 10, 12, 11, 12, 13, 14])
    del full[DAYS[4]]
    r = technical.rsi(3)(DAYS, full)
    assert (
        sorted(r) == [DAYS[3]]
    )  # days 0-3 are four consecutive bars; after the gap only days 5-7 remain, three bars, too few to start again


# ---- distance from the high and the low of the window ---------------------------------------------------------------
def test_dist_high_is_close_over_the_highest_close_of_the_window_minus_one_and_never_positive():
    bars = series([10, 12, 11, 9])
    r = technical.dist_high(3)(DAYS[:4], bars)
    assert sorted(r) == DAYS[2:4]  # window of three closes
    assert r[DAYS[2]][0] == D("-0.083333333333")  # 11 / 12 - 1
    assert r[DAYS[3]][0] == D("-0.25")  # 9 / 12 - 1
    assert all(v <= 0 for v, _ in r.values())


def test_dist_low_is_close_over_the_lowest_close_of_the_window_minus_one_and_never_negative():
    bars = series([10, 12, 11, 9])
    r = technical.dist_low(3)(DAYS[:4], bars)
    assert r[DAYS[2]][0] == D("0.1")  # 11 / 10 - 1
    assert r[DAYS[3]][0] == D("0")  # 9 is the low
    assert all(v >= 0 for v, _ in r.values())


# ---- volume ratio -----------------------------------------------------------------------------------------------------
def test_volume_ratio_is_the_short_mean_volume_over_the_long_mean_volume():
    bars = {d: bar(d, 10, raw_vol=v) for d, v in zip(DAYS[:4], (100, 200, 300, 400), strict=True)}
    r = technical.volume_ratio(2, 4)(DAYS[:4], bars)
    assert sorted(r) == [DAYS[3]] and r[DAYS[3]][0] == D(
        "1.4"
    )  # mean(300, 400) / mean(100..400) = 350 / 250


def test_volume_ratio_has_no_value_when_the_long_window_traded_nothing():
    bars = {d: bar(d, 10, raw_vol=0) for d in DAYS[:4]}
    assert technical.volume_ratio(2, 4)(DAYS[:4], bars) == {}


# ---- range volatility (Parkinson) ------------------------------------------------------------------------------------
def test_range_vol_is_the_parkinson_estimator_from_the_high_low_range():
    bars = {d: bar(d, 105, high=110, low=100) for d in DAYS[:2]}
    r = technical.range_vol(2)(DAYS[:2], bars)
    expected = math.log(1.1) / math.sqrt(4 * math.log(2))
    assert float(r[DAYS[1]][0]) == pytest.approx(expected, abs=1e-11)


def test_range_vol_of_a_day_with_no_range_is_zero_and_a_bad_low_gives_no_value():
    flat = {d: bar(d, 100) for d in DAYS[:2]}
    assert technical.range_vol(2)(DAYS[:2], flat)[DAYS[1]][0] == D("0")
    broken = {
        DAYS[0]: bar(DAYS[0], 100, high=110, low=100),
        DAYS[1]: bar(DAYS[1], 100, high=110, low=0),
    }
    assert technical.range_vol(2)(DAYS[:2], broken) == {}


# ---- maximum drawdown ---------------------------------------------------------------------------------------------------
def test_max_drawdown_is_the_deepest_fall_from_a_running_peak_inside_the_window():
    bars = series([10, 12, 9, 11])
    assert technical.max_drawdown(4)(DAYS[:4], bars)[DAYS[3]][0] == D("-0.25")  # peak 12, trough 9
    assert technical.max_drawdown(4)(DAYS[:4], series([10, 11, 12, 13]))[DAYS[3]][0] == D(
        "0"
    )  # only rises
    assert technical.max_drawdown(2)(DAYS[:4], bars)[DAYS[3]][0] == D(
        "0"
    )  # the window is (9, 11): the 12 is out of it


# ---- the rules every feature shares -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fn",
    [
        technical.rsi(3),
        technical.dist_high(3),
        technical.dist_low(3),
        technical.volume_ratio(2, 3),
        technical.range_vol(3),
        technical.max_drawdown(3),
    ],
)
def test_a_missing_session_gives_no_value_for_a_window_that_contains_it_and_warm_up_is_absent(fn):
    full = series([10, 12, 11, 9, 10, 11, 12, 13])
    assert min(fn(DAYS, full)) >= DAYS[2]  # nothing inside the warm-up
    del full[DAYS[4]]
    got = fn(DAYS, full)
    assert DAYS[4] not in got


def test_available_at_is_the_latest_of_every_input():
    bars = series([10, 12, 11, 9])
    late = bars[DAYS[1]]
    bars[DAYS[1]] = SessionBar(
        late.day,
        late.high,
        late.low,
        late.close,
        late.raw_close,
        late.raw_volume,
        at(DAYS[1], extra_hours=100),
    )
    assert technical.dist_high(3)(DAYS[:4], bars)[DAYS[2]][1] == at(DAYS[1], extra_hours=100)
    assert technical.dist_high(2)(DAYS[:4], bars)[DAYS[3]][1] == at(
        DAYS[3]
    )  # a window that does not reach the late bar is not delayed by it


def test_one_day_return_reuses_the_existing_return_function():
    bars = series([100, 102, 101])
    assert price.ret(1)(DAYS[:3], bars)[DAYS[1]][0] == D("0.02")

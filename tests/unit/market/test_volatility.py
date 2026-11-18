from datetime import date, timedelta

import numpy as np
import pytest

from algo.market import volatility as vol


def sessions(n, seed=1):
    rng = np.random.default_rng(seed)
    out, px = [], 100.0
    for i in range(n):
        wide = 0.5 + 1.5 * (i // 100 % 2)  # quiet and busy stretches of 100 sessions
        o = px * (1 + rng.normal(0, 0.002))
        c = o * (1 + rng.normal(0, 0.006 * wide))
        hi, lo = (
            max(o, c) * (1 + abs(rng.normal(0, 0.003 * wide))),
            min(o, c) * (1 - abs(rng.normal(0, 0.003 * wide))),
        )
        out.append(vol.Session(date(2020, 1, 1) + timedelta(days=i), o, hi, lo, c))
        px = c
    return out


def data(n=900):
    s = sessions(n)
    v = {
        x.day: 12 + 8 * (i // 100 % 2) for i, x in enumerate(s)
    }  # India VIX follows the busy stretches
    night = {x.day: (0.3, 1.0) for x in s}
    return vol.build(s, v, night)


def test_the_inputs_are_known_before_the_open_and_the_target_is_the_session_itself():
    s = sessions(60)
    v = {x.day: 15.0 for x in s}
    days, x, yr, ym = vol.build(s, v, {x.day: (1.0, -2.0) for x in s})
    assert days[0] == s[23].day and len(days) == len(s) - 23
    assert yr[0] == pytest.approx(vol.range_pct(s[23])) and ym[0] == pytest.approx(
        vol.move_pct(s[22].close, s[23])
    )
    assert x[0][0] == pytest.approx(np.log(vol.range_pct(s[22])))  # yesterday's range, not today's
    assert x[0][4] == pytest.approx(np.log(15.0)) and x[0][6] == -2.0


def test_a_session_with_no_vix_or_no_overnight_figure_is_skipped():
    s = sessions(40)
    days, *_ = vol.build(
        s, {x.day: 15.0 for x in s if x.day != s[-2].day}, {x.day: (0.0, 0.0) for x in s}
    )
    assert (
        s[-1].day not in days and len(days) == len(s) - 23 - 1
    )  # the day before it has no VIX close


def test_the_model_beats_yesterdays_value_when_ranges_come_in_busy_and_quiet_stretches():
    days, x, yr, _ = data()
    m = vol.walk_forward(x, yr)
    ok = ~np.isnan(m) & ~np.isnan(vol.persistence(yr))
    assert vol.errors(m[ok], yr[ok])[0] < vol.errors(vol.persistence(yr)[ok], yr[ok])[0]
    assert np.isnan(m[: vol.MIN_TRAIN]).all()  # nothing is predicted before enough has been seen


def test_the_walk_forward_never_uses_the_block_it_predicts():
    _, x, yr, _ = data()
    base = vol.walk_forward(x, yr)
    y2 = yr.copy()
    y2[vol.MIN_TRAIN + 5 :] += (
        100.0  # change everything from just after the first predicted block's start
    )
    changed = vol.walk_forward(x, y2)
    first = slice(vol.MIN_TRAIN, vol.MIN_TRAIN + vol.REFIT)
    assert np.allclose(
        base[first], changed[first]
    )  # the first block was fitted on earlier sessions only


def test_error_measures_and_change_direction():
    y, p = np.array([1.0, 2.0, 3.0]), np.array([1.5, 2.0, 2.0])
    assert vol.errors(p, y) == pytest.approx((0.5, np.sqrt((0.25 + 0 + 1) / 3)))
    assert (
        vol.change_direction_accuracy(
            np.array([2.0, 0.5]), np.array([3.0, 0.4]), np.array([1.0, 1.0])
        )
        == 1.0
    )
    assert (
        np.isnan(vol.trailing_mean(np.arange(10.0), 3)[:3]).all()
        and vol.trailing_mean(np.arange(10.0), 3)[3] == 1.0
    )

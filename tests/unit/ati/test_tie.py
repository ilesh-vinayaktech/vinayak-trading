"""TIE kill-test components: each is causal (prefix invariance + future mutation) and matches a hand-worked value."""

from typing import Any

import numpy as np
import pandas as pd

from algo.ati import tie

Arr = np.ndarray[Any, Any]


def panel(t: int = 300, s: int = 3, seed: int = 5) -> tuple[Arr, Arr, Arr, pd.DatetimeIndex]:
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, (t, s)), axis=0)
    h = c * (1 + np.abs(rng.normal(0, 0.008, (t, s))))
    lo = c * (1 - np.abs(rng.normal(0, 0.008, (t, s))))
    return h, lo, c, pd.bdate_range("2022-01-03", periods=t)


def all_features(h: Arr, lo: Arr, c: Arr, dates: pd.DatetimeIndex) -> dict[str, Arr]:
    atr = tie.atr(h, lo, c, 14)
    return {
        "er": tie.efficiency_ratio(c, 20),
        "slope": tie.regression_slope_atr(c, atr, 20),
        "swing": tie.swing_structure(h, lo, 3),
        "weekly": tie.weekly_trend(c, dates),
    }


def same(a: Arr, b: Arr) -> bool:
    return bool(np.array_equal(a, b, equal_nan=True))


def test_prefix_invariance_and_future_mutation() -> None:
    h, lo, c, dates = panel()
    full = all_features(h, lo, c, dates)
    for cut in (120, 151, 203):  # 151 and 203 are mid-week/pivot-confirmation days
        pre = all_features(h[:cut], lo[:cut], c[:cut], dates[:cut])
        h2, l2, c2 = h.copy(), lo.copy(), c.copy()
        h2[cut:], l2[cut:], c2[cut:] = h[cut:] * 3, lo[cut:] * 0.2, c[cut:] * 1.7
        mut = all_features(h2, l2, c2, dates)
        for k in full:
            assert same(full[k][:cut], pre[k]), (k, cut, "prefix")
            assert same(full[k][:cut], mut[k][:cut]), (k, cut, "mutation")


def test_efficiency_ratio_hand_values() -> None:
    straight = np.arange(1.0, 31.0)[:, None]
    assert tie.efficiency_ratio(straight, 10)[-1, 0] == 1.0
    zig = np.tile([1.0, 2.0], 15)[:, None]  # net 0 over 10 bars of total 10
    assert tie.efficiency_ratio(zig, 10)[-1, 0] == 0.0
    assert np.isnan(tie.efficiency_ratio(straight, 10)[9, 0])  # warm-up


def test_regression_slope_in_atr_units() -> None:
    c = (10 + 2.0 * np.arange(40))[:, None]
    atr = np.full_like(c, 4.0)
    out = tie.regression_slope_atr(c, atr, 20)
    assert np.isclose(out[-1, 0], 0.5)  # 2 per bar / ATR 4
    assert np.isnan(out[18, 0])


def test_swing_confirmation_delay_and_state() -> None:
    # rising zigzag; a pivot at bar i is first usable at bar i+k, never earlier
    k = 2
    base = np.array(
        [5, 6, 8, 6, 5, 6, 7, 10, 7, 6, 7, 9, 12, 9, 8, 9, 11, 14, 11, 10, 11, 13, 16, 13, 12],
        float,
    )
    h, lo = (base + 0.5)[:, None], (base - 0.5)[:, None]
    st = tie.swing_structure(h, lo, k)[:, 0]
    assert st[2 + k - 1] != 1  # pivot high at bar 2 is not confirmed before bar 4
    assert st[-1] == 1  # rising highs and lows
    assert np.isnan(st[0])


def test_weekly_trend_uses_only_completed_weeks() -> None:
    dates = pd.bdate_range("2023-01-02", periods=100)
    c = np.linspace(100, 200, 100)[:, None]
    w = tie.weekly_trend(c, dates)[:, 0]
    wk = dates.to_period("W-FRI")
    nxt = int(np.flatnonzero(wk != wk[0])[0])
    assert np.isnan(w[:nxt]).all()  # first week is not complete until week 2 starts
    assert w[-1] == 1.0  # steady rise: weekly up
    j = nxt + 60  # first day of week 13
    assert w[j + 3] == w[j] and np.isfinite(w[j])  # a forming week changes nothing

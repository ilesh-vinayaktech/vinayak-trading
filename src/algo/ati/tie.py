# ruff: noqa: E501
"""TIE kill-test components (2026-11-19): four causal trend measures not already in ati-f1. Inputs are days x stocks float arrays of ADJUSTED prices; row t uses sessions <= t only; NaN stays NaN.
SuperTrend and EMA alignment already live in `algo.ati.features`. This module adds Kaufman efficiency ratio, ATR-normalised regression slope, confirmed swing structure and weekly trend.
Pure functions: no clock, no I/O. Changing a formula means a new study, not a silent edit."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

Arr = np.ndarray[Any, Any]


def atr(h: Arr, lo: Arr, c: Arr, n: int) -> Arr:
    """Wilder ATR (RMA of the true range); NaN until n true ranges exist. Same definition as algo.ati.features._atr."""
    pc = np.vstack([np.full((1, c.shape[1]), np.nan), c[:-1]])
    tr = np.fmax(h - lo, np.fmax(np.abs(h - pc), np.abs(lo - pc)))
    return pd.DataFrame(tr).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy()


def efficiency_ratio(c: Arr, n: int) -> Arr:
    """Kaufman ER = |c[t] - c[t-n]| / sum of |daily change| over the same n sessions: 1 = straight line, 0 = no net move. Direction-free. NaN before n sessions."""
    d = np.abs(np.diff(c, axis=0, prepend=np.nan))
    net = np.abs(c - np.vstack([np.full((n, c.shape[1]), np.nan), c[:-n]]))
    path = pd.DataFrame(d).rolling(n, min_periods=n).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(path > 0, net / path, np.nan)
    out[:n] = np.nan
    return out


def regression_slope_atr(c: Arr, a: Arr, n: int) -> Arr:
    """OLS slope of the last n closes against bar number (price per bar), divided by the ATR at t: 'ATRs gained per bar'. Sign = direction. NaN before n sessions or without ATR."""
    t = c.shape[0]
    out = np.full(c.shape, np.nan)
    if t < n:
        return out
    x = np.arange(n) - (n - 1) / 2
    w = sliding_window_view(c, n, axis=0)  # (t-n+1, s, n)
    out[n - 1 :] = (w * x).sum(-1) / (x * x).sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(a > 0, out / a, np.nan)


def swing_structure(h: Arr, lo: Arr, k: int) -> Arr:
    """+1 higher-high AND higher-low, -1 lower-high AND lower-low, 0 mixed, NaN until two confirmed highs and two confirmed lows exist.
    A pivot high at bar i is the max high over i-k..i+k; it is only known at the close of bar i+k (the confirmation bar), never earlier: the pivot flag is shifted forward k bars before use."""

    def levels(x: Arr, hi: bool) -> tuple[Arr, Arr]:
        df = pd.DataFrame(x)
        ext = df.rolling(2 * k + 1, center=True, min_periods=2 * k + 1)
        piv = df.where(df == (ext.max() if hi else ext.min()))
        known = piv.shift(k)  # value appears on the confirmation bar
        last = known.ffill()
        before = last.shift(1).where(known.notna()).ffill()  # the previous confirmed pivot, as of the latest one
        return last.to_numpy(), before.to_numpy()

    hh, hp = levels(h, True)
    ll, lp = levels(lo, False)
    up = (hh > hp) & (ll > lp)
    dn = (hh < hp) & (ll < lp)
    out = np.where(up, 1.0, np.where(dn, -1.0, 0.0))
    return np.where(np.isfinite(hh) & np.isfinite(hp) & np.isfinite(ll) & np.isfinite(lp), out, np.nan)


def weekly_trend(c: Arr, dates: pd.DatetimeIndex, weeks: int = 10) -> Arr:
    """+1 / -1: the last COMPLETED week's close above / below its `weeks`-week simple average. A day in week w sees only weeks before w (a week counts as complete from the first session of the next one), so a forming week never leaks.
    NaN until `weeks` completed weeks exist. Weeks run Monday-Friday (W-FRI)."""
    wk = dates.to_period("W-FRI")
    wc = pd.DataFrame(c, index=dates).groupby(wk).last()
    avg = wc.rolling(weeks, min_periods=weeks).mean()
    sig = ((wc > avg).astype(float) * 2 - 1).where(avg.notna())
    return sig.shift(1).reindex(wk).to_numpy()

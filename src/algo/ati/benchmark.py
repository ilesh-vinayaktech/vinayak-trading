# ruff: noqa: E501
"""ATI P2 benchmarks (spec 11.4): forward returns measured against a matched group on the same day.
(Intervals: use `algo.backtest.validation.stats.bootstrap_interval`, the repo's stationary bootstrap; not duplicated here.)

`vol_deciles(vol)`: same-day cross-sectional decile (0 = calmest .. 9) of a known-at-t volatility measure; -1 where NaN. It uses only that day's other stocks, never the future.
`group_excess(fwd, groups, n_groups)`: for every day, the forward return minus the mean forward return of the stocks in the SAME group that day (group = volatility decile, or sector).
The group mean is over the stocks that have a forward return that day, the stock itself included (as for the plain same-day universe mean). NaN where the stock has no forward return or no group.
Pure functions of the arrays: no clock, no I/O."""

from __future__ import annotations

from typing import Any

import numpy as np

Arr = np.ndarray[Any, Any]


def vol_deciles(vol: Arr) -> Arr:
    """int8 days x stocks: the stock's decile of `vol` among the stocks that have it that day; -1 where `vol` is NaN."""
    out = np.full(vol.shape, -1, dtype="int8")
    for i in range(vol.shape[0]):
        ok = np.isfinite(vol[i])
        n = int(ok.sum())
        if n:
            rank = vol[i][ok].argsort(kind="stable").argsort(kind="stable")
            out[i, ok] = np.minimum(rank * 10 // n, 9)
    return out


def group_excess(fwd: Arr, groups: Arr, n_groups: int) -> Arr:
    """days x stocks of fwd minus the same-day mean of fwd within the same group (groups < 0 or NaN fwd -> NaN)."""
    t, s = fwd.shape
    ok = np.isfinite(fwd) & (groups >= 0)
    key = (np.arange(t)[:, None] * n_groups + np.where(ok, groups, 0)).ravel()
    tot = np.bincount(key, weights=np.where(ok, fwd, 0.0).ravel(), minlength=t * n_groups)
    cnt = np.bincount(key, weights=ok.ravel().astype(float), minlength=t * n_groups)
    mean = tot / np.maximum(cnt, 1)
    return np.where(ok, fwd - mean[key].reshape(t, s), np.nan)

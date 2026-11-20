# ruff: noqa: E501
"""ATR triple-barrier labels for the swing study (long only, daily bars, arrays shaped (sessions, stocks)).

A signal at the close of day t enters at the OPEN of day t+1. The ATR is the one known at t's close. Upper barrier = entry + up*ATR, lower = entry - dn*ATR,
vertical = the close of session t+horizon (entry day is session 1). Rules a daily bar cannot settle are made conservative and recorded:
- a session that OPENS beyond a barrier exits at that open (a gap), not at the barrier price;
- a session whose range touches both barriers is a LOSS at the lower barrier, flagged `ambiguous`;
- TIMEOUT rows keep their realised return, MFE and MAE.
Rows with no full window, a missing price or no ATR are NONE. Nothing after session t+horizon is read."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

Arr = npt.NDArray[Any]

NONE, PROFIT_FIRST, LOSS_FIRST, TIMEOUT = 0, 1, 2, 3


@dataclass(frozen=True)
class Labels:
    outcome: Arr  # int8 code above
    ret: Arr  # realised return entry -> exit (gross)
    sessions: Arr  # sessions held, entry day = 1
    mfe: Arr  # best high / entry - 1 up to the exit
    mae: Arr  # worst low / entry - 1 up to the exit
    ambiguous: Arr  # both barriers inside one bar


def atr(high: Arr, low: Arr, close: Arr, n: int = 14) -> Arr:
    """Simple mean of the true range over n sessions (NaN until n sessions exist)."""
    prev = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    tr = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    return pd.DataFrame(tr).rolling(n, min_periods=n).mean().to_numpy()


def barrier_labels(
    o: Arr,
    h: Arr,
    lo: Arr,
    c: Arr,
    atr_: Arr,
    up: float,
    dn: float,
    horizon: int,
) -> Labels:
    t, s = c.shape
    n = t - horizon  # signal days with a full window: 0 .. n-1 (window ends at n-1+horizon <= t-1)
    out = np.zeros((t, s), np.int8)
    ret = np.full((t, s), np.nan)
    held = np.zeros((t, s), np.int16)
    mfe = np.full((t, s), np.nan)
    mae = np.full((t, s), np.nan)
    amb = np.zeros((t, s), bool)
    if n <= 0:
        return Labels(out, ret, held, mfe, mae, amb)
    e = o[1 : n + 1]
    a = atr_[:n]
    upper: Arr = e + up * a
    lower: Arr = e - dn * a
    ok = np.isfinite(e) & np.isfinite(a) & (a > 0)
    for k in range(1, horizon + 1):  # session t+k
        sl = slice(k, n + k)
        ok &= np.isfinite(h[sl]) & np.isfinite(lo[sl]) & np.isfinite(c[sl])
    done = np.zeros((n, s), bool)
    o_ = np.zeros((n, s), np.int8)
    r_ = np.full((n, s), np.nan)
    k_ = np.zeros((n, s), np.int16)
    hi_run = np.full((n, s), -np.inf)
    lo_run = np.full((n, s), np.inf)
    mf = np.full((n, s), np.nan)
    ma = np.full((n, s), np.nan)
    am = np.zeros((n, s), bool)

    def close_out(mask: Arr, code: int, price: Arr, k: int) -> None:
        o_[mask] = code
        r_[mask] = (price / e - 1)[mask]
        k_[mask] = k
        mf[mask] = (hi_run / e - 1)[mask]
        ma[mask] = (lo_run / e - 1)[mask]
        done[mask] = True

    for k in range(1, horizon + 1):
        sl = slice(k, n + k)
        ob, hb, lb = o[sl], h[sl], lo[sl]
        live = ok & ~done
        hi_run = np.where(live, np.fmax(hi_run, hb), hi_run).reshape(n, s)
        lo_run = np.where(live, np.fmin(lo_run, lb), lo_run).reshape(n, s)
        if k > 1:
            gap_dn = live & (ob <= lower)
            gap_up = live & ~gap_dn & (ob >= upper)
            close_out(gap_dn, LOSS_FIRST, ob, k)
            close_out(gap_up, PROFIT_FIRST, ob, k)
            live = live & ~gap_dn & ~gap_up
        both = live & (hb >= upper) & (lb <= lower)
        am |= both
        loss = live & (lb <= lower)
        win = live & ~loss & (hb >= upper)
        close_out(loss, LOSS_FIRST, lower, k)
        close_out(win, PROFIT_FIRST, upper, k)
    close_out(ok & ~done, TIMEOUT, c[horizon : n + horizon], horizon)
    out[:n], ret[:n], held[:n], mfe[:n], mae[:n], amb[:n] = o_, r_, k_, mf, ma, am
    ret[:n][~ok], mfe[:n][~ok], mae[:n][~ok] = np.nan, np.nan, np.nan
    return Labels(out, ret, held, mfe, mae, amb)

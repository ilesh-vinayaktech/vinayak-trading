# ruff: noqa: E501
"""Extreme-move fade study (scripts/study_fade.py): the signal and the execution rejections, kept here so they can be tested.

Signal, known at the close of day T: the stock's previous-day return (close[T] / close[T-1] - 1) is at least +10.0% (a fixed number, frozen before the run). The trade, if it is one: sell short at the OPEN of T+1 and buy
back at the CLOSE of T+1 (an intraday short). A trade only counts as executable when no rejection below applies; every rejection is counted by reason. All inputs are known before the T+1 open, except the
outcome itself. Research code: floats on purpose."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

THRESHOLD = 0.10  # +10.0% previous-day return (frozen; the nearest round number below the lowest of the original model-matched cuts, 10.49%)
BANDS = (
    0.02,
    0.05,
    0.10,
    0.20,
)  # NSE daily price bands; when a stock's band is unknown any of them may apply
TICK = 0.05  # price tick, rupees: a limit price is rounded to it, so a low-priced stock's limit sits up to one tick inside the band
SLACK = 0.0005  # and a little rounding slack on top

OK, SERIES_T, SERIES_T1, BAD_OPEN, LOCKED_CLOSE, OPENS_AT_LIMIT, GSM = 0, 1, 2, 3, 4, 5, 6
REASONS = {
    OK: "executable (after the proxy filters)",
    SERIES_T: "not in the normal EQ series on the signal day",
    SERIES_T1: "no EQ bar on the entry day (moved to trade-for-trade, suspended or missing)",
    BAD_OPEN: "missing, zero or out-of-range opening price",
    LOCKED_CLOSE: "closed at its upper price-band limit and at the day's high (circuit-lock signature)",
    OPENS_AT_LIMIT: "opens at its upper price-band limit (nothing to short into, brokers block it)",
    GSM: "under a GSM stage on the entry day",
}


def previous_day_return(C: pd.DataFrame) -> pd.DataFrame:
    """close[T] / close[T-1] - 1, known at the close of T."""
    return C / C.shift(1) - 1


def extreme_up(C: pd.DataFrame, threshold: float = THRESHOLD) -> pd.DataFrame:
    """True where the previous-day return is at least `threshold` (a tiny tolerance keeps an exact +10.00% in)."""
    return previous_day_return(C) >= threshold - 1e-9


def at_upper_limit(
    change: NDArray[Any], base_price: NDArray[Any], band_pct: NDArray[Any] | None = None
) -> NDArray[np.bool_]:
    """True where `change` (a return against `base_price`) is at the stock's upper price-band limit, to within the tick rounding.
    `band_pct` is the band in percent (NaN or None = unknown: any of BANDS counts)."""
    ch = np.asarray(change, dtype=float)
    tol = TICK / np.maximum(np.asarray(base_price, dtype=float), 1e-9) + SLACK
    bp = np.full(ch.shape, np.nan) if band_pct is None else np.asarray(band_pct, dtype=float)
    band = bp / 100.0
    known = np.isfinite(band)
    hit_known = np.abs(ch - band) <= tol
    hit_any = np.zeros(ch.shape, dtype=bool)
    for b in BANDS:
        hit_any |= np.abs(ch - b) <= tol
    return np.asarray(np.where(known, hit_known, hit_any), dtype=bool)


def rejection_reason(
    *,
    series_t: Sequence[str | None],
    series_t1: Sequence[str | None],
    open_t1: NDArray[Any],
    low_t1: NDArray[Any],
    high_t1: NDArray[Any],
    close_t: NDArray[Any],
    high_t: NDArray[Any],
    prev_close_t: NDArray[Any],
    band_t1_pct: NDArray[Any] | None = None,
    gsm_t1: NDArray[Any] | None = None,
) -> NDArray[np.int64]:
    """Why a signal is NOT an executable short at the T+1 open (0 = it is), first reason wins, in this order: series on T, series on T+1, bad open, locked close on T, opening at the limit on T+1, GSM on T+1.
    Everything used is known before the T+1 open: the series and band lists are published before the session, the T bars are complete, and the T+1 open is the first print. (low_t1 / high_t1 are used only
    to reject an open that lies outside its own day's range, a data error, never to look at what the day did.)"""
    n = len(close_t)
    out = np.zeros(n, dtype=np.int64)
    s_t = np.array([s == "EQ" for s in series_t])
    s_t1 = np.array([s == "EQ" for s in series_t1])
    o = np.asarray(open_t1, dtype=float)
    good_open = (
        np.isfinite(o)
        & (o > 0)
        & (o >= np.asarray(low_t1, dtype=float))
        & (o <= np.asarray(high_t1, dtype=float))
    )
    prev = np.asarray(prev_close_t, dtype=float)
    ct = np.asarray(close_t, dtype=float)
    locked = at_upper_limit(ct / prev - 1, prev, None) & (
        ct >= np.asarray(high_t, dtype=float) * (1 - 1e-9)
    )
    opens_limit = at_upper_limit(o / ct - 1, ct, band_t1_pct)
    gsm = np.zeros(n, dtype=bool) if gsm_t1 is None else np.asarray(gsm_t1, dtype=bool)
    # first reason wins: assign from the lowest priority up so the highest priority overwrites
    for mask, code in (
        (gsm, GSM),
        (opens_limit & good_open, OPENS_AT_LIMIT),
        (locked, LOCKED_CLOSE),
        (~good_open, BAD_OPEN),
        (~s_t1, SERIES_T1),
        (~s_t, SERIES_T),
    ):
        out[mask] = code
    return out


def short_return(open_t1: NDArray[Any], close_t1: NDArray[Any]) -> NDArray[Any]:
    """An intraday short opened at the T+1 open and closed at the T+1 close: -(close / open - 1)."""
    r: NDArray[Any] = -(np.asarray(close_t1, dtype=float) / np.asarray(open_t1, dtype=float) - 1)
    return r

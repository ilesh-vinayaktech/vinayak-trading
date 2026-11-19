# ruff: noqa: E501
"""Trend-transition research (scripts/study_trend_transition.py): eligibility, barrier labels, feature groups E0/E1 and fixed technical baselines. RESEARCH ONLY.

Everything here is FROZEN by the owner's approval of 2026-11-19 and must not be tuned against a result. Every eligibility rule and feature uses bars of session T or earlier (tests/unit/research/test_trend_transition.py truncates
and scrambles the future to prove it); labels use sessions T+1.. only and live apart from the features. Inputs are date x stock panels (same index and columns). Research code: floats on purpose.

PRIOR DECLINE (both strategies): the lowest low of the last 60 sessions (L60) is at least 25% below the highest high of the last 120 sessions (H120): L60 <= 0.75 x H120.
EARLY (base forming, not confirmed): prior decline; the 60-session low was set at least 10 sessions ago; the last 20 sessions' (high - low) / low <= 25%; close <= the highest high of the previous 20 sessions and close < EMA50; close <= 1.20 x L60.
CONFIRMED (confirmed, not extended): prior decline; close > the highest high of the previous 20 sessions; close > EMA20 and > EMA50 and EMA20 above its value five sessions earlier; close <= 1.35 x L60 and no more than 3 ATR above EMA20.
OUTCOME from the next open (T+1): success = +8% reached before -4%, within 20 sessions (daily highs / lows); failed = -4% first; unresolved = neither; ambiguous = both inside one daily candle; incomplete = a needed bar is missing."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

UP, DOWN, HORIZON = 0.08, 0.04, 20
DECLINE, LOW_AGE, COMPRESSION, NOT_RECOVERED, NOT_EXTENDED_CONF, ATR_EXT = (
    0.25,
    10,
    0.25,
    1.20,
    1.35,
    3.0,
)
UNRESOLVED, SUCCESS, FAILED, AMBIGUOUS, INCOMPLETE = 0, 1, 2, 3, -1
OUTCOMES = {
    UNRESOLVED: "unresolved",
    SUCCESS: "success",
    FAILED: "failed",
    AMBIGUOUS: "ambiguous",
    INCOMPLETE: "incomplete",
}


def _ema(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def _atr(
    H: pd.DataFrame, L: pd.DataFrame, C: pd.DataFrame, n: int = 14
) -> tuple[pd.DataFrame, pd.DataFrame]:  # noqa: E741
    pc = C.shift(1)
    tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
    return tr, tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def prior_decline(H: pd.DataFrame, L: pd.DataFrame) -> pd.DataFrame:  # noqa: E741
    """L60 <= 0.75 x H120 (both windows must be full)."""
    return L.rolling(60).min() <= (1 - DECLINE) * H.rolling(120).max()


def early_eligible(H: pd.DataFrame, L: pd.DataFrame, C: pd.DataFrame) -> pd.DataFrame:  # noqa: E741
    l60 = L.rolling(60).min()
    old_low = L.shift(LOW_AGE).rolling(60 - LOW_AGE).min()  # sessions T-59 .. T-10
    recent_low = L.rolling(LOW_AGE).min()  # sessions T-9 .. T
    h20, l20 = H.rolling(20).max(), L.rolling(20).min()
    prior_high20 = H.shift(1).rolling(20).max()
    return (
        prior_decline(H, L)
        & (old_low <= recent_low)
        & ((h20 - l20) / l20 <= COMPRESSION)
        & (C <= prior_high20)
        & (C < _ema(C, 50))
        & (C <= NOT_RECOVERED * l60)
    )


def confirmed_eligible(H: pd.DataFrame, L: pd.DataFrame, C: pd.DataFrame) -> pd.DataFrame:  # noqa: E741
    l60 = L.rolling(60).min()
    prior_high20 = H.shift(1).rolling(20).max()
    e20, e50 = _ema(C, 20), _ema(C, 50)
    _, atr = _atr(H, L, C)
    return (
        prior_decline(H, L)
        & (C > prior_high20)
        & (C > e20)
        & (C > e50)
        & (e20 > e20.shift(5))
        & (C <= NOT_EXTENDED_CONF * l60)
        & ((C - e20) <= ATR_EXT * atr)
    )


def barrier_labels(
    O: NDArray[Any],  # noqa: E741
    H: NDArray[Any],
    L: NDArray[Any],
    C: NDArray[Any],
    ti: NDArray[Any],
    sj: NDArray[Any],
    up: float = UP,
    down: float = DOWN,
    horizon: int = HORIZON,
) -> dict[str, NDArray[Any]]:  # noqa: E741
    """Triple-barrier outcome for each signal (row ti, stock sj): entry = open of ti+1; sessions ti+1 .. ti+horizon are scanned in order with their daily high / low.
    A day whose high reaches the upside barrier AND whose low reaches the adverse barrier is AMBIGUOUS (never assumed favourable). A missing high or low before a barrier is reached makes the row INCOMPLETE.
    exit_ret = return from the entry open to where the position would leave: the barrier price, or that day's OPEN when it gaps through the barrier; unresolved = the close of session `horizon`; ambiguous = the adverse barrier
    (conservative). `k` is the 1-based session of the exit; `best` / `worst` are the highest high / lowest low reached up to it, from the entry open."""
    n = len(ti)
    T = O.shape[0]
    entry = np.full(n, np.nan)
    ok = ti + horizon < T
    entry[ok] = O[ti[ok] + 1, sj[ok]]
    ok &= np.isfinite(entry) & (entry > 0)
    code = np.where(ok, UNRESOLVED, INCOMPLETE).astype(np.int8)
    k_exit = np.full(n, horizon, dtype=np.int16)
    exit_ret = np.full(n, np.nan)
    best: NDArray[Any] = np.full(n, -np.inf)
    worst: NDArray[Any] = np.full(n, np.inf)
    done = ~ok
    upper, lower = entry * (1 + up), entry * (1 - down)
    for k in range(1, horizon + 1):
        idx = np.where(ok, ti + k, 0)
        h, low, o = H[idx, sj], L[idx, sj], O[idx, sj]
        missing = ~done & (~np.isfinite(h) | ~np.isfinite(low))
        code[missing] = INCOMPLETE
        done |= missing
        live = ~done
        best = np.where(live, np.maximum(best, h / entry - 1), best)
        worst = np.where(live, np.minimum(worst, low / entry - 1), worst)
        hit_up, hit_dn = live & (h >= upper), live & (low <= lower)
        amb, succ, fail = hit_up & hit_dn, hit_up & ~hit_dn, hit_dn & ~hit_up
        code[amb], code[succ], code[fail] = AMBIGUOUS, SUCCESS, FAILED
        k_exit[amb | succ | fail] = k
        exit_ret[amb] = -down
        exit_ret[succ] = (
            np.maximum(upper[succ], np.where(np.isfinite(o[succ]), o[succ], 0.0)) / entry[succ] - 1
        )  # a gap above the barrier fills at the open
        exit_ret[fail] = (
            np.minimum(lower[fail], np.where(np.isfinite(o[fail]), o[fail], np.inf)) / entry[fail]
            - 1
        )
        done |= amb | succ | fail
    unresolved = code == UNRESOLVED
    last = np.where(ok, ti + horizon, 0)
    exit_ret[unresolved] = C[last, sj][unresolved] / entry[unresolved] - 1
    code[unresolved & ~np.isfinite(exit_ret)] = INCOMPLETE
    return {
        "code": code,
        "k": k_exit,
        "exit_ret": exit_ret,
        "best": best,
        "worst": worst,
        "entry": entry,
    }


def features(
    O: pd.DataFrame,  # noqa: E741
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,  # noqa: E741
) -> dict[str, dict[str, Any]]:  # noqa: E741
    """E0 (price and volume) and E1-only (technical structure, momentum, volatility) feature panels, each known at the close of its own date."""
    pc = C.shift(1)
    tr, atr = _atr(H, L, C)
    ret1 = C / pc - 1
    rng = (H - L).replace(0, np.nan)
    vavg20 = V.rolling(20, min_periods=15).mean()
    h20, l20, h50, l50 = (
        H.rolling(20).max(),
        L.rolling(20).min(),
        H.rolling(50).max(),
        L.rolling(50).min(),
    )
    h252 = H.rolling(252, min_periods=200).max()
    l60, h120 = L.rolling(60).min(), H.rolling(120).max()
    up_v = V.where(C > pc, 0.0).rolling(10).sum()
    dn_v = V.where(C < pc, 0.0).rolling(10).sum()
    e0 = {
        "ret1": ret1, "ret2": C / C.shift(2) - 1, "ret3": C / C.shift(3) - 1, "ret5": C / C.shift(5) - 1, "ret10": C / C.shift(10) - 1, "ret20": C / C.shift(20) - 1,
        "gap": O / pc - 1, "intraday": C / O - 1, "range_pct": (H - L) / C, "body": (C - O) / rng, "upper_wick": (H - np.maximum(O, C)) / rng, "lower_wick": (np.minimum(O, C) - L) / rng,
        "relvol": V / vavg20, "vol5_20": V.rolling(5).mean() / vavg20, "updown_vol": up_v / dn_v.replace(0, np.nan),
        "dist_h20": C / h20 - 1, "dist_h50": C / h50 - 1, "dist_h252": C / h252 - 1, "rec_l20": C / l20 - 1, "rec_l50": C / l50 - 1, "rec_l60": C / l60 - 1, "dd_h120": C / h120 - 1,
    }  # fmt: skip
    e10, e20, e50, e200 = (_ema(C, n) for n in (10, 20, 50, 200))
    macd = _ema(C, 12) - _ema(C, 26)
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = (macd - sig) / C
    d = C.diff()
    rsi = 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    hv20, hv120 = ret1.rolling(20).std(), ret1.rolling(120, min_periods=100).std()
    hl = (L.rolling(10).min() > L.shift(10).rolling(10).min()).astype(float)
    lh = (H.rolling(10).max() < H.shift(10).rolling(10).max()).astype(float)
    tight = (((h20 - l20) / l20) < 0.12).to_numpy()
    cons = np.zeros(tight.shape, dtype=np.float32)
    for t in range(1, tight.shape[0]):
        cons[t] = np.where(tight[t], cons[t - 1] + 1, 0)
    e1 = {
        "d_e10": C / e10 - 1, "d_e20": C / e20 - 1, "d_e50": C / e50 - 1, "d_e200": C / e200 - 1, "e20_e50": e20 / e50 - 1, "e50_e200": e50 / e200 - 1,
        "e20_slope": e20 / e20.shift(5) - 1, "e50_slope": e50 / e50.shift(5) - 1, "e20_slope_chg": (e20 / e20.shift(5) - 1) - (e20.shift(5) / e20.shift(10) - 1),
        "higher_low": hl, "lower_high": lh, "above_e20_share": (C > e20).astype(float).rolling(20).mean(),
        "rsi": rsi, "rsi_chg5": rsi - rsi.shift(5), "macd": macd / C, "macd_sig": sig / C, "macd_hist": hist, "macd_hist_chg": hist - hist.shift(3),
        "mom_accel": (C / C.shift(5) - 1) - (C.shift(5) / C.shift(10) - 1), "roc10": C / C.shift(10) - 1,
        "cons_range20": (h20 - l20) / C, "range_compress": (h20 - l20) / (H.rolling(60).max() - L.rolling(60).min()), "breakout": (C > H.shift(1).rolling(20).max()).astype(float),
        "cons_sessions": pd.DataFrame(cons, index=C.index, columns=C.columns), "swing_hi_dist": C / H.shift(1).rolling(20).max() - 1, "swing_lo_dist": C / L.shift(1).rolling(20).min() - 1,
        "atr": atr / C, "atr_chg10": atr / atr.shift(10) - 1, "hv20": hv20, "hv_rel": hv20 / hv120, "range_expansion": tr / atr.shift(1), "atr_ratio_5_20": tr.rolling(5).mean() / tr.rolling(20).mean(),
    }  # fmt: skip
    return {"E0": e0, "E1": e1}


def baseline_rules(
    O: pd.DataFrame,  # noqa: E741
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,  # noqa: E741
) -> dict[str, pd.DataFrame]:  # noqa: E741
    """The six fixed technical rules, frozen: B1 close over EMA20 and EMA50; B2 EMA20 crossed above EMA50 within the last 3 sessions; B3 MACD crossed above its signal within the last 3 sessions;
    B4 RSI14 crossed above 50 within the last 3 sessions; B5 a close over the previous 20-session high out of a 20-session range of at most 25% with relative volume >= 1.5; B6 the combined screen (B1 and MACD histogram > 0 and RSI > 50 and relative volume >= 1.5)."""
    e20, e50 = _ema(C, 20), _ema(C, 50)
    macd = _ema(C, 12) - _ema(C, 26)
    sig = macd.ewm(span=9, adjust=False).mean()
    d = C.diff()
    rsi = 100 - 100 / (
        1
        + d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    relvol = V / V.rolling(20, min_periods=15).mean()
    h20, l20 = H.rolling(20).max(), L.rolling(20).min()
    b1 = (C > e20) & (C > e50)

    def within3(x: pd.DataFrame) -> pd.DataFrame:
        return x.astype(float).rolling(3).max() > 0

    return {
        "B1 close>EMA20&EMA50": b1,
        "B2 EMA20 x-up EMA50 (3d)": within3((e20 > e50) & (e20.shift(1) <= e50.shift(1))),
        "B3 MACD x-up signal (3d)": within3((macd > sig) & (macd.shift(1) <= sig.shift(1))),
        "B4 RSI x-up 50 (3d)": within3((rsi > 50) & (rsi.shift(1) <= 50)),
        "B5 range breakout + volume": (C > H.shift(1).rolling(20).max())
        & ((h20 - l20) / l20 <= 0.25)
        & (relvol >= 1.5),
        "B6 combined screen": b1 & ((macd - sig) > 0) & (rsi > 50) & (relvol >= 1.5),
    }


def walk_forward_masks(
    day_year: NDArray[Any],
    day_index: NDArray[Any],
    first_index_of_year: dict[int, int],
    purge: int = HORIZON + 1,
) -> dict[int, tuple[NDArray[Any], NDArray[Any]]]:
    """For each validation year: (train mask, validation mask) over rows. Training = every row whose day is more than `purge` sessions before the validation year starts (a training row's label looks `horizon`
    sessions ahead from the entry day, so nothing it looks at falls in the validation year); validation = the rows of that year."""
    return {
        y: (day_index < first - purge, day_year == y) for y, first in first_index_of_year.items()
    }

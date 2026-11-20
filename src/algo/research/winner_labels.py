# ruff: noqa: E501
"""Labels for the early-large-upside research (V2 spec, Phase A): what a signal taken after the close of session t would have earned if acted on.

Layout: every input is a days x stocks float array of ADJUSTED prices (NaN where a stock has no bar); row t of every output describes a signal after the close of session t.
Entry is the open of session t+1; the window is sessions t+1 .. t+horizon (the exit close of the fixed-horizon targets is the close of session t+horizon).

  Target A   close[t+h] / close[t] >= 1 + up                    the V1 label, close to close (not executable: it assumes the close of t)
  Target B   close[t+h] / open[t+1] - 1 at 5%, 8%, 10%          executable: next open to the horizon close
  Target C   first-passage outcome: +up barrier vs -down barrier, measured from the entry open
             SUCCESS / FAILURE / NO_EVENT (neither within h sessions: exit at the horizon close) / AMBIGUOUS (both touched on one daily candle: intraday order is unknown and is never guessed)
             A session that OPENS beyond a barrier exits at that open, not at the barrier (a gap is not a better fill). On the entry session the open IS the entry, so only the day's range can touch a barrier.

`valid` is False where the entry, the window or the exit has a missing price (a halt, a delisting, or the last rows with no full window). Invalid rows carry neutral values
(False / NO_EVENT / NaN): a caller must select on `valid`. Nothing here reads data before the entry open except Target A's close[t], or after the exit close.
Pure functions of the arrays: no clock, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

Arr = np.ndarray[Any, Any]

NO_EVENT, SUCCESS, FAILURE, AMBIGUOUS = 0, 1, 2, 3
B_LEVELS = (0.05, 0.08, 0.10)  # Target B thresholds, fixed by the spec


@dataclass(frozen=True)
class WinnerLabels:
    valid: Arr  # bool
    target_a: Arr  # bool
    ret_exec: Arr  # next open -> horizon close
    target_b_5: Arr  # bool
    target_b_8: Arr
    target_b_10: Arr
    outcome: Arr  # int8: NO_EVENT / SUCCESS / FAILURE / AMBIGUOUS
    exit_return: Arr  # realised return of the barrier trade (NaN when AMBIGUOUS or invalid)
    exit_session: (
        Arr  # int16: sessions after t on which the barrier trade ends (0 when AMBIGUOUS or invalid)
    )
    mfe: Arr  # best high of the window / entry - 1
    mae: Arr  # worst low of the window / entry - 1
    max_ret: Arr  # best close of the window / entry - 1
    min_ret: Arr  # worst close of the window / entry - 1
    s5: Arr  # first session whose high is >= entry +5% (NaN if never)
    s8: Arr
    s10: Arr
    sm5: Arr  # first session whose low is <= entry -5%


def _ahead(x: Arr, k: int) -> Arr:
    """Row t holds the value of session t+k (NaN past the end)."""
    out = np.full_like(x, np.nan)
    if k < len(x):
        out[:-k] = x[k:]
    return out


def winner_labels(
    o: Arr, h: Arr, lo: Arr, c: Arr, *, horizon: int = 10, up: float = 0.10, down: float = 0.05
) -> WinnerLabels:
    o, h, lo, c = (np.asarray(a, dtype="float64") for a in (o, h, lo, c))
    entry = _ahead(o, 1)
    c_exit = _ahead(c, horizon)
    target, stop = entry * (1 + up), entry * (1 - down)

    valid = np.isfinite(entry) & np.isfinite(c) & np.isfinite(c_exit)
    outcome = np.full(o.shape, NO_EVENT, dtype=np.int8)
    exit_px = np.full(o.shape, np.nan)
    exit_session = np.zeros(o.shape, dtype=np.int16)
    unresolved = np.ones(o.shape, dtype=bool)
    best_h = np.full(o.shape, -np.inf)
    worst_l = np.full(o.shape, np.inf)
    best_c = np.full(o.shape, -np.inf)
    worst_c = np.full(o.shape, np.inf)
    first = {k: np.full(o.shape, np.nan) for k in ("s5", "s8", "s10", "sm5")}

    with np.errstate(invalid="ignore"):
        for d in range(1, horizon + 1):
            od, hd, ld, cd = _ahead(o, d), _ahead(h, d), _ahead(lo, d), _ahead(c, d)
            valid &= np.isfinite(od) & np.isfinite(hd) & np.isfinite(ld) & np.isfinite(cd)
            best_h, worst_l = np.fmax(best_h, hd), np.fmin(worst_l, ld)
            best_c, worst_c = np.fmax(best_c, cd), np.fmin(worst_c, cd)
            for key, hit in (
                ("s5", hd >= entry * 1.05),
                ("s8", hd >= entry * 1.08),
                ("s10", hd >= entry * 1.10),
                ("sm5", ld <= entry * 0.95),
            ):
                first[key] = np.where(np.isnan(first[key]) & hit, d, first[key])
            # a session that opens beyond a barrier exits at the open (never on the entry session: its open is the entry)
            gap_up = unresolved & (d > 1) & (od >= target)
            gap_dn = unresolved & (d > 1) & (od <= stop) & ~gap_up
            free = unresolved & ~gap_up & ~gap_dn
            touch_up, touch_dn = free & (hd >= target), free & (ld <= stop)
            both = touch_up & touch_dn
            succ, fail = gap_up | (touch_up & ~both), gap_dn | (touch_dn & ~both)
            outcome = np.where(
                succ, SUCCESS, np.where(fail, FAILURE, np.where(both, AMBIGUOUS, outcome))
            ).astype(np.int8)
            exit_px = np.where(
                gap_up | gap_dn,
                od,
                np.where(touch_up & ~both, target, np.where(touch_dn & ~both, stop, exit_px)),
            )
            done = succ | fail | both
            exit_session = np.where(done & (exit_session == 0), d, exit_session).astype(np.int16)
            unresolved &= ~done

        exit_px = np.where(unresolved, c_exit, exit_px)  # neither barrier: out at the horizon close
        exit_session = np.where(unresolved, horizon, exit_session).astype(np.int16)
        exit_return = exit_px / entry - 1
        ret_exec = c_exit / entry - 1

        ambiguous = outcome == AMBIGUOUS
        outcome[~valid] = NO_EVENT
        exit_session[~valid | ambiguous] = 0
        exit_return[~valid | ambiguous] = np.nan

        def nan_inv(x: Arr) -> Arr:
            return np.where(valid, x, np.nan)

        ret_exec = nan_inv(ret_exec)
        return WinnerLabels(
            valid=valid,
            target_a=valid & (c_exit / c >= 1 + up),
            ret_exec=ret_exec,
            target_b_5=valid & (ret_exec >= B_LEVELS[0]),
            target_b_8=valid & (ret_exec >= B_LEVELS[1]),
            target_b_10=valid & (ret_exec >= B_LEVELS[2]),
            outcome=outcome,
            exit_return=exit_return,
            exit_session=exit_session,
            mfe=nan_inv(best_h / entry - 1),
            mae=nan_inv(worst_l / entry - 1),
            max_ret=nan_inv(best_c / entry - 1),
            min_ret=nan_inv(worst_c / entry - 1),
            s5=nan_inv(first["s5"]),
            s8=nan_inv(first["s8"]),
            s10=nan_inv(first["s10"]),
            sm5=nan_inv(first["sm5"]),
        )

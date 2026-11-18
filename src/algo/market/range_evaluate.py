# ruff: noqa: E501
"""The frozen forward test of the expected-range forecast (spec docs/forecast/volatility_v1_spec.md, section 7): the model's mean absolute error against the 5-session-average baseline on the same sessions,
with a paired moving-block bootstrap interval. Nothing is computed below the minimum number of sessions, so a growing sample cannot be checked early."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from algo.market import evaluate as ev

MIN_SESSIONS = 500
Arr = NDArray[np.float64]


def mae_gap(
    base: Arr, model: Arr, y: Arr, *, reps: int, block: int = 20, seed: int = 20261119
) -> tuple[float, float, float]:
    """MAE of the baseline minus MAE of the model (positive: the model has the smaller error), with a two-sided 95% paired moving-block bootstrap interval."""

    def gap(i: NDArray[np.intp]) -> float:
        return float(np.mean(np.abs(base[i] - y[i])) - np.mean(np.abs(model[i] - y[i])))

    lo, hi = ev.block_ci(gap, len(y), block=block, reps=reps, seed=seed)
    return gap(np.arange(len(y))), lo, hi


def primary_test(
    base5: Arr, model: Arr, y: Arr, *, min_sessions: int = MIN_SESSIONS, reps: int = 10_000
) -> dict[str, object]:
    """The one promotion test: below `min_sessions` it returns only the count; at or above it, the gap, its interval and whether the lower bound is above zero (forward-validated)."""
    n = len(y)
    if n < min_sessions:
        return {"sessions": n, "evaluated": False}
    gap, lo, hi = mae_gap(base5, model, y, reps=reps)
    return {
        "sessions": n,
        "evaluated": True,
        "delta": gap,
        "low": lo,
        "high": hi,
        "validated": lo > 0,
    }


def segment_mae(
    labels: list[str], model: Arr, base: Arr, y: Arr, *, min_n: int = 30
) -> dict[str, tuple[int, float, float]]:
    """(sessions, model MAE, baseline MAE) for each label with at least `min_n` sessions."""
    lab = np.array(labels)
    out = {}
    for seg in sorted(set(labels)):
        m = lab == seg
        if m.sum() >= min_n:
            out[seg] = (
                int(m.sum()),
                float(np.mean(np.abs(model[m] - y[m]))),
                float(np.mean(np.abs(base[m] - y[m]))),
            )
    return out

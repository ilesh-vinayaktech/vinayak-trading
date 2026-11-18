# ruff: noqa: E501
"""How good is a probability forecast of "up"? (forecast validation.) Everything a forecast is judged on, on identical days, with the uncertainty that
neighbouring days bring: accuracy, Brier score and skill against a reference, log loss, ROC-AUC, precision and recall, the confusion matrix, calibration by probability
bucket, a split by market regime, and a moving-block bootstrap for confidence intervals (days next to each other are not independent, least of all for 5-day outcomes).
References are built only from outcomes already known on each day (expanding frequencies), never from the whole sample. Pure functions on arrays; statistics, so floats."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Arr = NDArray[np.float64]
EDGES = (
    0.0,
    0.40,
    0.45,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    1.0001,
)  # probability buckets for calibration


@dataclass(frozen=True)
class Metrics:
    n: int
    ups: int
    downs: int
    accuracy: float
    brier: float
    log_loss: float
    auc: float | None  # None when only one outcome occurs
    precision: float | None  # of the days called up (p above 0.5), the share that rose
    recall: float | None  # of the days that rose, the share called up
    tp: int
    fp: int
    fn: int
    tn: int


def brier(p: Arr, y: Arr) -> float:
    return float(np.mean((p - y) ** 2))


def brier_skill(p: Arr, y: Arr, ref: Arr) -> float:
    """1 - Brier(model) / Brier(reference): above 0 beats the reference."""
    r = brier(ref, y)
    return 1.0 - brier(p, y) / r if r > 0 else 0.0


def log_loss(p: Arr, y: Arr) -> float:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def auc(p: Arr, y: Arr) -> float | None:
    """Probability that a day that rose was given a higher p than a day that did not (ties count half)."""
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    allv = np.concatenate([pos, neg])[order]
    i = 0
    while i < len(allv):  # average ranks over ties
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def metrics(p: Arr, y: Arr) -> Metrics:
    called = p > 0.5
    up = y == 1
    tp, fp, fn, tn = (
        int((called & up).sum()),
        int((called & ~up).sum()),
        int((~called & up).sum()),
        int((~called & ~up).sum()),
    )
    return Metrics(
        len(y), int(up.sum()), int((~up).sum()), float(np.mean(called == up)), brier(p, y), log_loss(p, y), auc(p, y),
        tp / (tp + fp) if tp + fp else None, tp / (tp + fn) if tp + fn else None, tp, fp, fn, tn,
    )  # fmt: skip


def calibration(p: Arr, y: Arr, edges: Sequence[float] = EDGES) -> list[dict[str, float | int]]:
    """Per probability bucket: how many days, the average probability said, and the share that really rose. Buckets with no day are left out."""
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (p >= lo) & (p < hi)
        if m.any():
            out.append(
                {
                    "from": lo,
                    "to": min(hi, 1.0),
                    "n": int(m.sum()),
                    "said": float(p[m].mean()),
                    "actual": float(y[m].mean()),
                }
            )
    return out


def expanding_base(y: Arr, horizon: int) -> Arr:
    """For each day, the share of outcomes that rose among those already known then (a day's outcome is known `horizon` days later); 0.5 before any is known."""
    out = np.full(len(y), 0.5)
    cs = np.cumsum(y)
    for i in range(len(y)):
        k = i - horizon  # the last day whose outcome is known on day i
        if k >= 0:
            out[i] = cs[k] / (k + 1)
    return out


def expanding_conditional(signal: Arr, y: Arr, horizon: int, min_obs: int = 30) -> Arr:
    """Like `expanding_base` but separately for days with signal True and False (yesterday rose, the 21-day trend is up, ...); the plain base before `min_obs` such days."""
    base = expanding_base(y, horizon)
    out = base.copy()
    for i in range(len(y)):
        k = i - horizon
        if k < 0:
            continue
        past = signal[: k + 1] == signal[i]
        if past.sum() >= min_obs:
            out[i] = y[: k + 1][past].mean()
    return out


def block_resample(n: int, block: int, rng: np.random.Generator) -> NDArray[np.intp]:
    """Indices for one moving-block bootstrap sample of n days: random runs of `block` consecutive days stitched together."""
    block = max(1, min(block, n))
    starts = rng.integers(0, n - block + 1, size=-(-n // block))
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def block_ci(
    stat: Callable[[NDArray[np.intp]], float],
    n: int,
    block: int = 20,
    reps: int = 1000,
    seed: int = 7,
    level: float = 0.95,
) -> tuple[float, float]:
    """A (low, high) interval for `stat` (a function of the day indices) by moving-block bootstrap."""
    rng = np.random.default_rng(seed)
    vals = np.array([stat(block_resample(n, block, rng)) for _ in range(reps)])
    a = (1 - level) / 2
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def by_segment(
    labels: Sequence[str], p: Arr, y: Arr, ref: Arr, min_n: int = 30
) -> Mapping[str, dict[str, float | int]]:
    """Accuracy and Brier skill (against `ref`) for each regime label with at least `min_n` days: an overall figure can hide a regime where the model is poor."""
    lab = np.array(labels)
    out = {}
    for seg in sorted(set(labels)):
        m = lab == seg
        if m.sum() >= min_n:
            out[seg] = {
                "n": int(m.sum()),
                "accuracy": float(np.mean((p[m] > 0.5) == (y[m] == 1))),
                "brier_skill": brier_skill(p[m], y[m], ref[m]),
                "base_rate": float(y[m].mean()),
            }
    return out


MIN_PAIRS = 500  # the frozen promotion test needs this many paired forward days; before that nothing is computed, so there is nothing to peek at


def primary_test(
    p_prod: Arr,
    p_cand: Arr,
    y: Arr,
    *,
    min_pairs: int = MIN_PAIRS,
    reps: int = 10_000,
    block: int = 20,
    seed: int = 20261119,
) -> dict[str, object]:
    """The frozen promotion test of a candidate against production: delta = Brier(production) - Brier(candidate) on the same days (positive favours the candidate), with a
    two-sided 95% paired moving-block bootstrap interval. Promotion is allowed only when the interval's lower bound is above zero. With fewer than `min_pairs` days it returns
    only the count (no estimate, no interval), so an accumulating sample cannot be checked early."""
    n = len(y)
    if n < min_pairs:
        return {"pairs": n, "evaluated": False}

    def gap(idx: NDArray[np.intp]) -> float:
        return brier(p_prod[idx], y[idx]) - brier(p_cand[idx], y[idx])

    lo, hi = block_ci(gap, n, block=block, reps=reps, seed=seed)
    return {
        "pairs": n,
        "evaluated": True,
        "delta": gap(np.arange(n)),
        "low": lo,
        "high": hi,
        "promote": lo > 0,
    }

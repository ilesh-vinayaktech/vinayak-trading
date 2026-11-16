# ruff: noqa: E501
"""The statistics of alpha discovery (plan.md section 6): rank information coefficient, a Newey-West corrected test of its mean, and multiple-testing
adjustment. Pure functions on plain numbers (these are statistics, not money). Nothing here knows about a database, a clock or the holdout.

The information coefficient (IC) of a feature on a day is the Spearman rank correlation, across the stocks, between the feature's value and the stocks'
later return. Returns over a horizon of h sessions overlap from one day to the next, so the daily IC series is autocorrelated: the mean's standard error
uses a Bartlett-weighted (Newey-West) long-run variance with lag h - 1, otherwise the test would claim far more certainty than the data holds."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()


def ranks(xs: Sequence[float]) -> list[float]:
    """1-based ranks, ties given the average of the ranks they span."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys):
        raise ValueError("spearman needs two series of the same length")
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / math.sqrt(sxx * syy)


def cross_sectional_ic(
    feature: Mapping[int, float], forward: Mapping[int, float], *, min_names: int
) -> float | None:
    """The day's IC over the stocks that have BOTH a feature value and a forward return; None when fewer than `min_names` do."""
    both = sorted(set(feature) & set(forward))
    if len(both) < min_names:
        return None
    return spearman([feature[i] for i in both], [forward[i] for i in both])


@dataclass(frozen=True)
class Summary:
    n: int  # days with an IC
    mean: float | None
    std: float | None
    icir: float | None  # mean / std: the signal-to-noise of the daily IC
    hit_rate: float | None  # share of days with a positive IC
    t_stat: float | None  # mean over its Newey-West standard error
    p_value: float | None  # two-sided, normal approximation


def summarise(ics: Sequence[float], *, lag: int) -> Summary:
    """`lag` is the overlap of the horizon (h - 1): the number of autocovariances the long-run variance includes."""
    n = len(ics)
    if n == 0:
        return Summary(0, None, None, None, None, None, None)
    mean = sum(ics) / n
    hit = sum(1 for x in ics if x > 0) / n
    if n < 2:
        return Summary(n, mean, None, None, hit, None, None)
    dev = [x - mean for x in ics]
    std = math.sqrt(sum(d * d for d in dev) / (n - 1))
    icir = None if std == 0 else mean / std
    gamma0 = sum(d * d for d in dev) / n
    lrv = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        gamma_k = sum(dev[i] * dev[i - k] for i in range(k, n)) / n
        lrv += 2 * (1 - k / (lag + 1)) * gamma_k
    if lrv <= 0:
        return Summary(n, mean, std, icir, hit, None, None)
    t = mean / math.sqrt(lrv / n)
    return Summary(n, mean, std, icir, hit, t, 2 * (1 - _N.cdf(abs(t))))


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm's step-down adjustment (controls the family-wise error rate), returned in the input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    out = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        out[i] = running
    return out


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg q-values: the smallest false discovery rate at which each test would be called a discovery. Valid for positively dependent tests (the same feature at several
    horizons is that case). The q-value of the i-th smallest of m p-values is the smallest of p_j x m / j over every j at or above it, capped at one; ties share a value."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    for k in range(
        m
    ):  # equal p-values get the smallest q among them (a tie is not broken by order)
        for j in range(m):
            if pvalues[j] == pvalues[k] and q[j] < q[k]:
                q[k] = q[j]
    return q


def bonferroni(pvalues: Sequence[float], *, total_tests: int) -> list[float]:
    """Each p-value times the number of tests EVER run (this batch and every earlier one), capped at one."""
    if total_tests < len(pvalues):
        raise ValueError("total_tests must be at least the number of p-values given")
    return [min(1.0, p * total_tests) for p in pvalues]

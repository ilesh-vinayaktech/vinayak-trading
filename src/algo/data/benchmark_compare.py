"""Cross-index consistency of two benchmark series (e.g. Nifty 200 vs Nifty 50 gross TRI).

Returns are computed per series on its OWN consecutive observations, before any join, so a session
missing on one side is never bridged silently: a date is compared only if both series have a return
for it over the SAME previous date. Everything else is reported, never dropped quietly. This is a
consistency check between related indices, not an independent verification of either."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def daily_returns(levels: Mapping[date, Decimal]) -> dict[date, tuple[date, float]]:
    """day -> (previous observed day, TRI_t / TRI_prev - 1), from one series alone."""
    days = sorted(levels)
    return {b: (a, float(levels[b] / levels[a] - 1)) for a, b in zip(days, days[1:], strict=False)}


@dataclass(frozen=True)
class Divergence:
    day: date
    ret_a: float
    ret_b: float
    diff: float  # ret_a - ret_b


@dataclass(frozen=True)
class Comparison:
    overlap: tuple[date, date]  # first and last date present in BOTH series
    compared: int  # dates with a return on both sides over the same previous date
    only_a: tuple[date, ...]  # dates in A inside the overlap that B lacks
    only_b: tuple[date, ...]
    misaligned: tuple[date, ...]  # both have the date but over different previous dates
    correlation: float
    max_abs_diff: float
    p99_abs_diff: float
    largest: tuple[Divergence, ...]
    cumulative_a: float  # first to last compared date, each from its own levels
    cumulative_b: float


def percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    vx, vy = sum((a - mx) ** 2 for a in x), sum((b - my) ** 2 for b in y)
    return cov / math.sqrt(vx * vy) if vx and vy else math.nan  # a constant series has none


def compare(a: Mapping[date, Decimal], b: Mapping[date, Decimal], top: int = 20) -> Comparison:
    lo, hi = max(min(a), min(b)), min(max(a), max(b))
    if lo >= hi:
        raise ValueError("the series do not overlap")
    ra, rb = daily_returns(a), daily_returns(b)
    only_a = tuple(sorted(d for d in a if lo <= d <= hi and d not in b))
    only_b = tuple(sorted(d for d in b if lo <= d <= hi and d not in a))
    both = sorted(d for d in ra if d in rb and lo < d <= hi)
    aligned = [d for d in both if ra[d][0] == rb[d][0]]
    misaligned = tuple(d for d in both if ra[d][0] != rb[d][0])
    if len(aligned) < 2:
        raise ValueError("fewer than two comparable dates")
    xa, xb = [ra[d][1] for d in aligned], [rb[d][1] for d in aligned]
    diffs = [x - y for x, y in zip(xa, xb, strict=True)]
    absd = sorted(abs(d) for d in diffs)
    worst = sorted(zip(aligned, xa, xb, diffs, strict=True), key=lambda t: -abs(t[3]))[:top]
    first = ra[aligned[0]][0]
    return Comparison(
        (lo, hi), len(aligned), only_a, only_b, misaligned, correlation(xa, xb), absd[-1],
        percentile(absd, 0.99), tuple(Divergence(*t) for t in worst),
        float(a[aligned[-1]] / a[first] - 1), float(b[aligned[-1]] / b[first] - 1),
    )  # fmt: skip

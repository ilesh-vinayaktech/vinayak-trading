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


@dataclass(frozen=True)
class Wedge:
    """Total-return minus price-return daily, over the dates both series can be compared on."""

    compared: int
    only_price: tuple[date, ...]
    only_tri: tuple[date, ...]
    misaligned: tuple[date, ...]
    price_beats_tri: tuple[tuple[date, float], ...]  # price rose more than TRI beyond rounding
    wedge_days: int  # days where TRI exceeds price beyond rounding
    top5pct_share: float  # share of the total wedge carried by the largest 5% of days
    by_year: tuple[tuple[int, float], ...]  # summed daily wedge per year (~ dividend yield)
    largest: tuple[Divergence, ...]  # biggest |wedge| days, ret_a = TRI, ret_b = price


def wedge(price: Mapping[date, Decimal], tri: Mapping[date, Decimal], top: int = 20) -> Wedge:
    """A dividend-paying index must have TRI return >= price return on every day, except for the
    rounding of two-decimal levels (reported per date as `price_beats_tri`, never hidden)."""
    lo, hi = max(min(price), min(tri)), min(max(price), max(tri))
    rp, rt = daily_returns(price), daily_returns(tri)
    only_p = tuple(sorted(d for d in price if lo <= d <= hi and d not in tri))
    only_t = tuple(sorted(d for d in tri if lo <= d <= hi and d not in price))
    both = sorted(d for d in rp if d in rt and lo < d <= hi)
    aligned = [d for d in both if rp[d][0] == rt[d][0]]
    misaligned = tuple(d for d in both if rp[d][0] != rt[d][0])
    diffs = {d: rt[d][1] - rp[d][1] for d in aligned}
    tol = {d: float(Decimal("0.02") / min(price[rp[d][0]], tri[rt[d][0]])) for d in aligned}
    neg = tuple((d, diffs[d]) for d in aligned if diffs[d] < -tol[d])
    pos = sorted((diffs[d] for d in aligned if diffs[d] > tol[d]), reverse=True)
    total = sum(pos)
    k = max(1, math.ceil(0.05 * len(pos))) if pos else 0
    years: dict[int, float] = {}
    for d in aligned:
        years[d.year] = years.get(d.year, 0.0) + diffs[d]
    worst = sorted(aligned, key=lambda d: -abs(diffs[d]))[:top]
    share = sum(pos[:k]) / total if total else 0.0
    return Wedge(
        len(aligned), only_p, only_t, misaligned, neg, len(pos), share,
        tuple(sorted(years.items())),
        tuple(Divergence(d, rt[d][1], rp[d][1], diffs[d]) for d in worst),
    )  # fmt: skip

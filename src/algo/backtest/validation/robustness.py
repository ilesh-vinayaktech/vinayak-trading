"""Is the result a property of the strategy, or of one lucky parameter setting / year / stock?"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from algo.backtest.validation.stats import sharpe_per_period


def perturbations(params: Mapping[str, Any], pct: float = 0.2) -> list[dict[str, Any]]:
    """One-at-a-time +/-pct changes of every numeric parameter (ints stay ints, min 1)."""
    out = []
    for k, v in params.items():
        if isinstance(v, bool) or not isinstance(v, int | float):
            continue
        for f in (1 - pct, 1 + pct):
            nv = max(1, round(v * f)) if isinstance(v, int) else v * f
            if nv != v:
                out.append({**params, k: nv})
    return out


@dataclass(frozen=True)
class Plateau:
    base: float
    worst: float
    worst_drop: float  # fraction of the base Sharpe lost at the worst neighbour
    stable: bool


def plateau(base: float, neighbours: Sequence[float | None], tolerance: float = 0.3) -> Plateau:
    """Stable when every neighbouring setting keeps at least (1 - tolerance) of the base Sharpe.
    An undefined neighbour counts as a collapse."""
    if base <= 0:
        return Plateau(base, min((n for n in neighbours if n is not None), default=0.0), 1.0, False)
    vals = [-1e9 if n is None else n for n in neighbours]
    worst = min(vals, default=base)
    drop = max(0.0, (base - worst) / base)
    return Plateau(base, worst, drop, drop <= tolerance + 1e-9)


def by_year(days: Sequence[date], returns: Sequence[float]) -> dict[int, dict[str, float | None]]:
    if len(days) != len(returns):
        raise ValueError("days and returns differ in length")
    groups: dict[int, list[float]] = defaultdict(list)
    for d, r in zip(days, returns, strict=True):
        groups[d.year].append(r)
    out: dict[int, dict[str, float | None]] = {}
    for y, rs in sorted(groups.items()):
        total = 1.0
        for r in rs:
            total *= 1 + r
        out[y] = {"return": total - 1, "sharpe": sharpe_per_period(rs), "days": float(len(rs))}
    return out


def concentration(contributions: Mapping[str, float], top: int = 3) -> float:
    """Share of the total POSITIVE contribution that comes from the `top` best items
    (instruments, years...). 1.0 means the result is just those few."""
    gains = sorted((v for v in contributions.values() if v > 0), reverse=True)
    total = sum(gains)
    return 0.0 if total == 0 else sum(gains[:top]) / total

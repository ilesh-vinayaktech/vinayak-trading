"""Validation of a captured benchmark series BEFORE it is ingested. Pure functions over parsed
observations. Nothing is repaired: conflicts and gaps are reported, never resolved silently."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from algo.data.providers.niftyindices_tri import Observation


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class WindowResponse:
    start: date  # the window that was requested
    end: date
    observations: tuple[Observation, ...]


@dataclass
class Validation:
    checks: list[Check] = field(default_factory=list)
    levels: dict[date, Decimal] = field(default_factory=dict)  # consolidated only if consistent
    largest_moves: list[tuple[Decimal, date]] = field(default_factory=list)  # to investigate
    gaps: list[tuple[date, date]] = field(default_factory=list)  # calendar gaps over the threshold

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]


def validate_series(
    responses: Sequence[WindowResponse], *, base_date: date, base_level: Decimal, gap_days: int = 5
) -> Validation:
    v = Validation()
    seen: dict[date, list[Decimal]] = {}
    outside: list[date] = []
    for w in responses:
        for o in w.observations:
            seen.setdefault(o.day, []).append(o.level)
            if not w.start <= o.day <= w.end:
                outside.append(o.day)
    dup = sorted(d for d, lv in seen.items() if len(lv) > 1)
    conflicts = sorted(d for d in dup if len(set(seen[d])) > 1)
    v.checks.append(
        Check(
            "duplicate_dates",
            not dup,
            f"{len(dup)} dates occur more than once {[str(d) for d in dup[:5]]}",
        )
    )
    v.checks.append(
        Check(
            "conflicting_values",
            not conflicts,
            f"{len(conflicts)} dates have different values {[str(d) for d in conflicts[:5]]}",
        )
    )
    v.checks.append(
        Check(
            "inside_requested_window",
            not outside,
            f"{len(outside)} rows outside their window {[str(d) for d in sorted(outside)[:5]]}",
        )
    )
    bad = sorted(d for d, lv in seen.items() if any(x <= 0 for x in lv))
    v.checks.append(
        Check(
            "positive_levels",
            not bad,
            f"{len(bad)} non-positive levels {[str(d) for d in bad[:5]]}",
        )
    )
    if not seen:
        v.checks.append(Check("not_empty", False, "no observations"))
        return v
    days = sorted(seen)
    v.checks.append(
        Check(
            "first_observation", days[0] == base_date, f"first is {days[0]}, expected {base_date}"
        )
    )
    first = seen[days[0]][0]
    v.checks.append(
        Check("base_level", first == base_level, f"first level {first}, expected {base_level}")
    )
    if not conflicts:
        v.levels = {d: seen[d][0] for d in days}
    v.gaps = [(a, b) for a, b in zip(days, days[1:], strict=False) if (b - a).days > gap_days]
    if v.levels:
        moves = [
            (abs(v.levels[b] / v.levels[a] - 1), b) for a, b in zip(days, days[1:], strict=False)
        ]
        v.largest_moves = sorted(moves, reverse=True)[:10]
    return v


@dataclass(frozen=True)
class Session:
    day: date
    kind: str  # REGULAR | SPECIAL | MUHURAT


def compare_sessions(
    series_days: Iterable[date], known: Iterable[date]
) -> tuple[list[date], list[date]]:
    """(benchmark dates the calendar lacks, calendar sessions with no benchmark value)."""
    have, cal = set(series_days), set(known)
    return sorted(have - cal), sorted(cal - have)


@dataclass(frozen=True)
class ReturnCheck:
    label: str
    base: date
    end: date
    kind: str  # "cumulative" | "cagr"
    published_pct: Decimal
    tolerance_pp: Decimal


@dataclass(frozen=True)
class ReturnResult:
    check: ReturnCheck
    computed_pct: Decimal
    difference_pp: Decimal
    passed: bool


def reconcile_returns(
    levels: dict[date, Decimal], checks: Iterable[ReturnCheck]
) -> list[ReturnResult]:
    """Recompute each published return from the stored levels. CAGR uses calendar days / 365.25 (the
    convention is recorded, not assumed); the difference is reported even when within tolerance."""
    out = []
    for c in checks:
        if c.base not in levels or c.end not in levels:
            raise KeyError(f"{c.label}: no level for {c.base if c.base not in levels else c.end}")
        ratio = float(levels[c.end] / levels[c.base])
        if c.kind == "cumulative":
            computed = Decimal(str((ratio - 1) * 100))
        elif c.kind == "cagr":
            years = (c.end - c.base).days / 365.25
            computed = Decimal(str((ratio ** (1 / years) - 1) * 100))
        else:
            raise ValueError(f"unknown return kind {c.kind!r}")
        diff = computed - c.published_pct
        out.append(ReturnResult(c, computed, diff, abs(diff) <= c.tolerance_pp))
    return out

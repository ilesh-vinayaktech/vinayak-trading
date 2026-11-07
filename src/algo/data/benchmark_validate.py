"""Validation of a captured benchmark series BEFORE it is ingested. Pure functions over parsed
observations. Nothing is repaired: conflicts and gaps are reported, never resolved silently."""

from __future__ import annotations

import hashlib
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
    responses: Sequence[WindowResponse],
    *,
    base_date: date,
    base_level: Decimal | None,
    gap_days: int = 5,
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
    if (
        base_level is not None
    ):  # None: the base level is not independently documented, so not checked
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


RATIO_TOLERANCE = Decimal("0.00002")  # levels are rounded to 2 decimals
JUMP_TOLERANCE = Decimal("0.003")  # a one-day change of the net/gross ratio worth investigating


def validate_net(gross: dict[date, Decimal], net: dict[date, Decimal]) -> Validation:
    """Consistency of a NET total-return series with the GROSS one it is published beside. Net can
    only lose value to gross (tax removes dividends), so the ratio net/gross must never rise.
    Nothing is filled: coverage is reported as found, never extended."""
    v = Validation(levels=dict(net))
    if not net:
        v.checks.append(Check("net_populated", False, "no net observations"))
        return v
    days = sorted(net)
    first = days[0]
    v.checks.append(Check("net_populated", True, f"first valid net date {first}, last {days[-1]}"))
    stray = sorted(d for d in net if d not in gross)
    v.checks.append(
        Check(
            "net_dates_in_gross",
            not stray,
            f"{len(stray)} net dates have no gross value {[str(d) for d in stray[:5]]}",
        )
    )
    missing = sorted(d for d in gross if d >= first and d not in net)
    v.checks.append(
        Check(
            "net_contiguous",
            not missing,
            f"{len(missing)} gross dates after {first} lack a net value "
            f"{[str(d) for d in missing[:5]]}",
        )
    )
    starts_equal = first in gross and net[first] == gross[first]
    v.checks.append(
        Check(
            "net_starts_at_gross",
            starts_equal,
            f"net {net[first]} vs gross {gross.get(first)} on {first}",
        )
    )
    shared = [d for d in days if d in gross]
    ratio = {d: net[d] / gross[d] for d in shared}
    rises = [
        d
        for a, d in zip(shared, shared[1:], strict=False)
        if ratio[d] - ratio[a] > RATIO_TOLERANCE * ratio[a]
    ]
    v.checks.append(
        Check(
            "net_never_gains_on_gross",
            not rises,
            f"{len(rises)} days where net/gross rises {[str(d) for d in rises]}",
        )
    )
    jumps = sorted(
        ((abs(ratio[d] / ratio[a] - 1), d) for a, d in zip(shared, shared[1:], strict=False)),
        reverse=True,
    )
    v.largest_moves = jumps[:10]  # for ratios these are one-day changes of net/gross
    big = [d for j, d in jumps if j > JUMP_TOLERANCE]
    v.checks.append(
        Check(
            "no_abrupt_net_gross_jump",
            not big,
            f"{len(big)} days with a ratio change > {JUMP_TOLERANCE} {[str(d) for d in big]}",
        )
    )
    v.gaps = [(a, b) for a, b in zip(days, days[1:], strict=False) if (b - a).days > 5]
    return v


REPORT_VERSION = "2"
ACCEPTANCE_STATES = ("ACCEPTED_WITH_EVIDENCE", "UNRESOLVED")


@dataclass(frozen=True)
class Finding:
    """A failed check the owner has looked at. It never changes the check: the check stays FAIL in
    `technical_validation_passed`; this only says what is known about it."""

    check: str
    state: str  # ACCEPTED_WITH_EVIDENCE | UNRESOLVED
    label: str
    reason: str
    detail_sha256: str  # binds the acceptance to the exact flagged dates


def parse_acceptances(specs: Iterable[str], checks: Sequence[Check]) -> list[Finding]:
    """`CHECK=STATE:LABEL:REASON`. Rejects malformed specs, unknown checks, empty labels/reasons,
    duplicates, and acceptance of a check that did not fail."""
    by_name = {c.name: c for c in checks}
    out: dict[str, Finding] = {}
    for spec in specs:
        name, _, rest = spec.partition("=")
        parts = rest.split(":", 2)
        if not name or len(parts) != 3:
            raise ValueError(f"malformed acceptance {spec!r}: want CHECK=STATE:LABEL:REASON")
        state, label, reason = (p.strip() for p in parts)
        if name not in by_name:
            raise ValueError(f"{name}: no such check (have {sorted(by_name)})")
        if state not in ACCEPTANCE_STATES:
            raise ValueError(f"{name}: state must be one of {ACCEPTANCE_STATES}, got {state!r}")
        if not label or not reason:
            raise ValueError(f"{name}: label and reason must not be empty")
        if name in out:
            raise ValueError(f"{name}: accepted twice")
        if by_name[name].passed:
            raise ValueError(f"{name}: the check passed, there is nothing to accept")
        digest = hashlib.sha256(by_name[name].detail.encode()).hexdigest()
        out[name] = Finding(name, state, label, reason, digest)
    return list(out.values())


def check_states(checks: Sequence[Check], findings: Sequence[Finding]) -> dict[str, str]:
    """PASS | FAIL | ACCEPTED_WITH_EVIDENCE | UNRESOLVED for every check."""
    by_name = {f.check: f.state for f in findings}
    return {c.name: "PASS" if c.passed else by_name.get(c.name, "FAIL") for c in checks}

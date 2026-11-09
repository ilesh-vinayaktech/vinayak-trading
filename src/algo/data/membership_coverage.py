"""Per-session evidence for point-in-time index membership. Pure logic: callers pass plain data.

Each trading session is classified on separate axes, never folded into one score:
  completeness       COMPLETE | INCOMPLETE: every member is a tradable instrument with a bar
  knowledge          CONTEMPORANEOUS | RETROSPECTIVE: was every member's state that day already
                     published by that day's decision? A change whose only evidence is a later
                     release is retrospective until the release date (a plausible effective date,
                     but a lookahead risk)
  independent_check  CHECKPOINTED | RELEASE_ONLY: an official snapshot series covers the session
  verification       VERIFIED | PROVISIONAL: person-verified
Strict-eligible = COMPLETE, CONTEMPORANEOUS and VERIFIED. The independent-check axis is evidence
quality and does not block by itself. A release dated d counts as known at d's close."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MemberSpan:
    entity: str  # "i:<instrument_id>" | "s:<symbol>" (no instrument) | "p:<placeholder>"
    start: date
    end: date | None  # exclusive


@dataclass(frozen=True)
class Event:
    entity: str
    effective: date
    announced: date


@dataclass(frozen=True)
class SessionCoverage:
    day: date
    members: tuple[str, ...]
    members_hash: str
    untradable: tuple[str, ...]
    missing_bars: tuple[str, ...]
    retrospective: tuple[str, ...]
    completeness: str
    knowledge: str
    independent_check: str
    verification: str

    @property
    def eligible_once_verified(self) -> bool:
        return self.completeness == "COMPLETE" and self.knowledge == "CONTEMPORANEOUS"

    @property
    def strict_eligible(self) -> bool:
        return self.eligible_once_verified and self.verification == "VERIFIED"

    @property
    def reasons(self) -> tuple[str, ...]:
        return (
            *(f"member without an instrument: {e}" for e in self.untradable),
            *(f"member without a bar: {e}" for e in self.missing_bars),
            *(f"membership not yet published at the decision: {e}" for e in self.retrospective),
            *(("membership not person-verified",) if self.verification != "VERIFIED" else ()),
        )


def session_coverage(
    sessions: Iterable[date],
    spans: Sequence[MemberSpan],
    events: Sequence[Event],
    has_bar: Callable[[int, date], bool],
    checked_until: date | None,
    verified: bool,
) -> list[SessionCoverage]:
    out = []
    for d in sessions:
        members = tuple(
            sorted({s.entity for s in spans if s.start <= d and (s.end is None or d < s.end)})
        )
        untradable = tuple(e for e in members if not e.startswith("i:"))
        missing = tuple(e for e in members if e.startswith("i:") and not has_bar(int(e[2:]), d))
        retro = tuple(sorted({e.entity for e in events if e.effective <= d < e.announced}))
        digest = hashlib.sha256(",".join(members).encode()).hexdigest()
        checked = checked_until is not None and d <= checked_until
        out.append(
            SessionCoverage(
                d, members, digest, untradable, missing, retro,
                "INCOMPLETE" if untradable or missing else "COMPLETE",
                "RETROSPECTIVE" if retro else "CONTEMPORANEOUS",
                "CHECKPOINTED" if checked else "RELEASE_ONLY",
                "VERIFIED" if verified else "PROVISIONAL",
            )
        )  # fmt: skip
    return out


def unusable_days(coverage: Iterable[SessionCoverage]) -> dict[date, str]:
    """Sessions a strict decision must skip, with the reasons (for the strategy's strict gate)."""
    return {c.day: "; ".join(c.reasons) for c in coverage if not c.strict_eligible}

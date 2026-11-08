"""Pure logic for rebuilding index membership BACKWARD from a verified current snapshot.

For each component (Nifty 50, Next 50, Midcap 100 ...) the current members are known; every
published INCLUDED / EXCLUDED transition is undone newest-first, so the state before a transition is
(state after - included) + excluded. Rules that keep this honest:
  * an inconsistent transition is recorded as a discrepancy and never forced into a tidy answer
  * undated, future-dated and pre-window transitions are not applied (undated ones are reported)
  * entities are instruments, unmapped symbols or placeholders: they are never merged by guesswork
  * where the reconstruction disagrees with an independent snapshot, ONLY the disagreeing entity is
    blocked, from the last agreeing snapshot to the next one
No database access: callers pass plain data and persist nothing here."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

Entity = str  # "i:<instrument_id>" | "s:<symbol>" (unmapped) | "p:<symbol>" (placeholder)
Members = frozenset[Entity]


def entity_of(instrument_id: int | None, symbol: str, mapping_status: str) -> Entity:
    if instrument_id is not None:
        return f"i:{instrument_id}"
    return f"p:{symbol}" if mapping_status == "PLACEHOLDER_SECURITY" else f"s:{symbol}"


@dataclass(frozen=True)
class Transition:
    component: str
    entity: Entity
    symbol: str
    action: str  # INCLUDED | EXCLUDED
    effective: date | None  # first day the change applies (a date, never inferred)
    announced: date
    doc_id: str
    section: str
    source_hash: str
    parser_version: str
    page: int


@dataclass(frozen=True)
class Step:
    day: date
    before: dict[str, Members]
    after: dict[str, Members]
    applied: tuple[Transition, ...]


@dataclass
class Walk:
    start: date
    anchor_date: date
    steps: list[Step]  # oldest first
    initial: dict[str, Members]  # state on `start`
    discrepancies: list[dict[str, object]] = field(default_factory=list)
    unplaced: list[Transition] = field(default_factory=list)
    future: list[Transition] = field(default_factory=list)


def walk_back(
    anchor: Mapping[str, Members], transitions: Iterable[Transition], start: date, anchor_date: date
) -> Walk:  # fmt: skip
    comps = list(anchor)
    unique = {(x.component, x.entity, x.action, x.effective): x for x in transitions
              if x.component in anchor}  # fmt: skip
    rows = list(unique.values())
    walk = Walk(start, anchor_date, [], {})
    walk.unplaced = [x for x in rows if x.effective is None]
    walk.future = [x for x in rows if x.effective is not None and x.effective > anchor_date]
    usable = [x for x in rows if x.effective is not None and start < x.effective <= anchor_date]
    cur = {c: set(anchor[c]) for c in comps}
    for day in sorted({x.effective for x in usable if x.effective}, reverse=True):
        after = {c: frozenset(cur[c]) for c in comps}
        todays = [x for x in usable if x.effective == day]
        for c in comps:
            inc = {x.entity for x in todays if x.component == c and x.action == "INCLUDED"}
            exc = {x.entity for x in todays if x.component == c and x.action == "EXCLUDED"}
            for e in sorted(inc & exc):
                walk.discrepancies.append(_d("SAME_DAY_BOTH", day, c, e))
            for e in sorted(inc - cur[c]):
                walk.discrepancies.append(_d("INCLUDED_BUT_NOT_MEMBER_AFTER", day, c, e))
            for e in sorted(exc & cur[c]):
                walk.discrepancies.append(_d("EXCLUDED_BUT_MEMBER_AFTER", day, c, e))
            cur[c] = (cur[c] - inc) | exc
        walk.steps.append(Step(day, {c: frozenset(cur[c]) for c in comps}, after, tuple(todays)))
    walk.steps.reverse()
    walk.initial = {c: frozenset(cur[c]) for c in comps}
    return walk


def _d(kind: str, day: date, comp: str, entity: Entity) -> dict[str, object]:
    return {"kind": kind, "day": day, "component": comp, "entity": entity}


def _union(state: Mapping[str, Members], comps: Sequence[str]) -> Members:
    return frozenset().union(*(state[c] for c in comps))


@dataclass(frozen=True)
class Event:
    day: date
    entity: Entity
    kind: str  # ADD | REMOVE
    announced: date  # when the change became known: the latest announcement among its sources
    sources: tuple[Transition, ...]


def union_events(walk: Walk, comps: Sequence[str]) -> list[Event]:
    """Entities entering or leaving the union of components. Moves between components net out."""
    out: list[Event] = []
    for s in walk.steps:
        b, a = _union(s.before, comps), _union(s.after, comps)
        for kind, ents in (("ADD", a - b), ("REMOVE", b - a)):
            for e in ents:
                src = tuple(x for x in s.applied if x.entity == e and x.component in comps)
                out.append(Event(s.day, e, kind, max(x.announced for x in src), src))
    return sorted(out, key=lambda x: (x.day, x.entity, x.kind))


@dataclass(frozen=True)
class Interval:
    entity: Entity
    start: date
    end: date | None  # first day NOT a member; None = still a member at the anchor
    start_basis: str


def intervals_from(walk: Walk, comps: Sequence[str], start: date, end: date) -> list[Interval]:
    open_: dict[Entity, tuple[date, str]] = {
        e: (start, "WINDOW_START_BACKWARD_WALK") for e in _union(walk.initial, comps)
    }
    out: list[Interval] = []
    for ev in union_events(walk, comps):
        if ev.day > end:
            continue
        if ev.kind == "ADD":
            open_[ev.entity] = (ev.day, "EVENT")
        else:
            s, basis = open_.pop(ev.entity)
            out.append(Interval(ev.entity, s, ev.day, basis))
    out.extend(Interval(e, s, None, basis) for e, (s, basis) in open_.items())
    return sorted(out, key=lambda i: (i.entity, i.start))


def state_on(walk: Walk, comps: Sequence[str], day: date) -> Members:
    cur = _union(walk.initial, comps)
    for s in walk.steps:
        if s.day <= day:
            cur = _union(s.after, comps)
    return cur


def reconcile(
    walk: Walk, comps: Sequence[str], snapshots: Mapping[date, Members], coverage: str = "FULL"
) -> list[dict[str, object]]:  # fmt: skip
    """Compare the reconstructed union with independent snapshots inside the window. `coverage` is
    FULL when the snapshot speaks for the whole union, PARTIAL when it covers only part of it (an
    entity absent from both sides then proves nothing)."""
    for c in comps:
        if c not in walk.initial:
            raise KeyError(c)
    out: list[dict[str, object]] = []
    for d in sorted(snapshots):
        if not walk.start <= d <= walk.anchor_date:
            continue
        rec, snap = state_on(walk, comps, d), snapshots[d]
        out.append({"date": d, "snapshot": len(snap), "reconstructed": len(rec),
                    "only_in_snapshot": sorted(snap - rec),
                    "only_in_reconstruction": sorted(rec - snap),
                    "common": sorted(rec & snap), "coverage": coverage})  # fmt: skip
    return out


def combine_rows(
    full: Sequence[dict[str, object]], partial: Sequence[dict[str, object]]
) -> list[dict[str, object]]:  # fmt: skip
    """One chronological list; where both exist for a date the FULL comparison wins."""
    by_date = {r["date"]: r for r in partial}
    by_date.update({r["date"]: r for r in full})
    return [by_date[d] for d in sorted(by_date)]  # type: ignore[type-var]


def block_windows(
    rec: Sequence[Mapping[str, object]], start: date, end: date
) -> dict[Entity, list[tuple[date, date]]]:  # fmt: skip
    """Per entity, the smallest justified span in which the reconstruction cannot be trusted: from
    the day after the last agreeing snapshot to the next agreeing one (window edges if none). A
    PARTIAL snapshot is silent about an entity absent from both sides, so it neither confirms nor
    contradicts it."""
    bad = {e for r in rec for e in (*r["only_in_snapshot"], *r["only_in_reconstruction"])}  # type: ignore[misc]
    out: dict[Entity, list[tuple[date, date]]] = {}
    for e in sorted(bad):
        rows: list[tuple[date, bool]] = []  # (date, is_mismatch) for the rows that speak about e
        for r in rec:
            if e in r["only_in_snapshot"] or e in r["only_in_reconstruction"]:  # type: ignore[operator]
                rows.append((r["date"], True))  # type: ignore[arg-type]
            elif e in r.get("common", ()) or r.get("coverage", "FULL") == "FULL":  # type: ignore[operator]
                rows.append((r["date"], False))  # type: ignore[arg-type]
        i = 0
        while i < len(rows):
            if not rows[i][1]:
                i += 1
                continue
            j = i
            while j + 1 < len(rows) and rows[j + 1][1]:
                j += 1
            lo = rows[i - 1][0] + timedelta(days=1) if i > 0 else start
            hi = rows[j + 1][0] if j + 1 < len(rows) else end
            out.setdefault(e, []).append((lo, hi))
            i = j + 1
    return out

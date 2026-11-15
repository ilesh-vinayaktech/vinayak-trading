# ruff: noqa: E501
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
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

Entity = str  # "i:<instrument_id>" | "s:<symbol>" (unmapped) | "p:<symbol>" (placeholder)
Members = frozenset[Entity]


def entity_of(instrument_id: int | None, symbol: str, mapping_status: str) -> Entity:
    if instrument_id is not None:
        return f"i:{instrument_id}"
    return f"p:{symbol}" if mapping_status == "PLACEHOLDER_SECURITY" else f"s:{symbol}"


def equivalence_map(records: Iterable[Mapping[str, object]]) -> dict[Entity, Entity]:
    """From reviewed records {"from": [entity, ...], "to": "i:<id>"} to a flat map. Two keys of ONE
    issuer (an unmapped symbol before an alias starts, then the instrument) are then compared as one
    entity. This never touches an identity table and refuses ambiguity: a target must be an
    instrument or a pre-listing symbol, nothing maps to itself, twice, or through a chain."""
    out: dict[Entity, Entity] = {}
    for rec in records:
        target = str(rec["to"])
        if not target.startswith(("i:", "s:")):
            raise ValueError(f"{target} must be an instrument or a pre-listing symbol")
        for src in rec["from"]:  # type: ignore[attr-defined]
            if src == target:
                raise ValueError(f"{src} maps to itself")
            if src in out:
                raise ValueError(f"{src} is mapped twice")
            out[src] = target
    if any(v in out for v in out.values()):
        raise ValueError("an equivalence chain is not allowed")
    return out


def unify_entities(
    trs: Sequence[Transition], equivalent: Mapping[Entity, Entity]
) -> list[Transition]:
    return [replace(x, entity=equivalent.get(x.entity, x.entity)) for x in trs]


def closing_entity(
    instrument_id: int | None,
    symbol: str,
    mapping_status: str,
    related: str | None,
    action: str,
    replaced: frozenset[str] = frozenset(),
) -> Entity:
    """The entity a release row acts on. An EXCLUSION whose release names the dummy symbol it
    replaces ends the placeholder's membership, unless a reviewed replacement record hands that
    dummy over to the listing (`replaced`): then the exclusion acts on the listing itself.
    Entities are still never merged, and no identity table is touched."""
    if action == "EXCLUDED" and related and related.startswith("DUMMY") and related not in replaced:
        return f"p:{related}"
    return entity_of(instrument_id, symbol, mapping_status)


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
class Revocation:
    """A later release revoked one announced change: same release, index, stock, kind and date."""

    doc_id: str  # the release that announced the change
    authority_doc: str  # the release that revokes it
    component: str
    symbol: str
    action: str  # the announced action that is cancelled: INCLUDED | EXCLUDED
    effective: date


def apply_revocations(
    trs: Sequence[Transition], revs: Sequence[Revocation]
) -> tuple[list[Transition], list[tuple[Revocation, Transition]], list[Revocation]]:
    """Cancel each revoked transition (never invent a compensating one). Returns the transitions
    that remain, the (revocation, cancelled transition) pairs, and revocations that matched
    nothing: those are reported, never silently dropped."""
    cancelled: list[tuple[Revocation, Transition]] = []
    unmatched: list[Revocation] = []
    gone: set[int] = set()
    for rv in revs:
        hit = next(
            (
                i
                for i, tr in enumerate(trs)
                if i not in gone
                and (tr.doc_id, tr.component, tr.symbol, tr.action, tr.effective)
                == (rv.doc_id, rv.component, rv.symbol, rv.action, rv.effective)
            ),
            None,
        )
        if hit is None:
            unmatched.append(rv)
        else:
            gone.add(hit)
            cancelled.append((rv, trs[hit]))
    return [tr for i, tr in enumerate(trs) if i not in gone], cancelled, unmatched


@dataclass(frozen=True)
class Void:
    """A later release declared the changes one release announced for one effective date null and void (for example the 2020-05-13 release
    voiding the replacements of 18 February, 12 March and 19 March 2020 that were due on 27 March 2020)."""

    doc_id: str  # the release whose changes are void
    effective: date  # only the changes it announced for this date; changes it announced for other dates stand
    authority_doc: str  # the release that declares them void


def apply_voids(
    trs: Sequence[Transition], voids: Sequence[Void]
) -> tuple[list[Transition], list[tuple[Void, Transition]], list[Void]]:
    """Drop every transition a void covers (same release, same effective date). Returns the transitions that remain, the (void, dropped
    transition) pairs, and voids that matched nothing: reported, never silently ignored. Nothing is invented in their place."""
    dropped: list[tuple[Void, Transition]] = []
    matched: set[Void] = set()
    kept: list[Transition] = []
    for tr in trs:
        hit = next((v for v in voids if (v.doc_id, v.effective) == (tr.doc_id, tr.effective)), None)
        if hit is None:
            kept.append(tr)
        else:
            dropped.append((hit, tr))
            matched.add(hit)
    return kept, dropped, [v for v in voids if v not in matched]


@dataclass(frozen=True)
class Replacement:
    """A reviewed record: the listing `symbol` (entity `entity`) took over from the zero-price
    placeholder `placeholder` on `listed_on`, as the exclusion release `evidence_doc` states."""

    placeholder: str
    entity: Entity
    symbol: str
    listed_on: date
    evidence_doc: str
    placeholder_entity: Entity | None = None  # default p:<placeholder>; s:<symbol> when pre-alias


def apply_replacements(
    trs: Sequence[Transition], reps: Sequence[Replacement]
) -> tuple[list[Transition], list[Replacement]]:
    """Add the handover on the listing date, per index the placeholder was in: the placeholder
    leaves and the listing joins. Entities stay separate; originals are untouched. Returns the
    transitions and the replacements that had nothing to hand over (reported, never dropped)."""
    out = list(trs)
    unmatched: list[Replacement] = []
    for rep in reps:
        ph = rep.placeholder_entity or f"p:{rep.placeholder}"
        added: list[Transition] = []
        for comp in sorted({x.component for x in trs if x.entity == ph and x.action == "INCLUDED"}):
            began = any(
                x.entity == ph and x.component == comp and x.action == "INCLUDED"
                and x.effective is not None and x.effective < rep.listed_on
                for x in trs
            )  # fmt: skip
            ended = next(
                (
                    x
                    for x in trs
                    if x.entity == rep.entity and x.component == comp and x.action == "EXCLUDED"
                    and x.effective is not None and x.effective > rep.listed_on
                ),
                None,
            )  # fmt: skip
            if began and ended:
                for ent, sym, act in (
                    (ph, rep.placeholder, "EXCLUDED"),
                    (rep.entity, rep.symbol, "INCLUDED"),
                ):
                    added.append(Transition(
                        comp, ent, sym, act, rep.listed_on, ended.announced, rep.evidence_doc,
                        "placeholder replacement", ended.source_hash,
                        ended.parser_version, ended.page,
                    ))  # fmt: skip
        if added:
            out.extend(added)
        else:
            unmatched.append(rep)
    return out, unmatched


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


HANDOVER_BASIS = "ISIN_CHANGE_HANDOVER"
IsinChange = tuple[int, int, date]  # (source instrument, target instrument, effective date)


def hand_over_isin_changes(
    intervals: Sequence[Interval], changes: Sequence[IsinChange]
) -> list[Interval]:
    """Membership follows the INSTRUMENT that trades. For each VERIFIED ISIN change (the caller
    passes only those), membership of either instrument is cut at the effective date: before it the
    source holds it, from it the target does, so the issuer is a member continuously and the two are
    never members on one day. The end is exclusive: the source's last member day is the day before
    the change. Only a split interval gets the HANDOVER start basis; others keep their own."""
    out = list(intervals)
    for src, tgt, eff in changes:
        pair = {f"i:{src}", f"i:{tgt}"}
        nxt: list[Interval] = []
        for iv in out:
            if iv.entity not in pair:
                nxt.append(iv)
                continue
            if iv.start < eff:
                nxt.append(replace(iv, entity=f"i:{src}", end=min(iv.end, eff) if iv.end else eff))
            if iv.end is None or iv.end > eff:
                crossed = iv.start < eff
                nxt.append(
                    Interval(
                        f"i:{tgt}",
                        max(iv.start, eff),
                        iv.end,
                        HANDOVER_BASIS if crossed else iv.start_basis,
                    )
                )
        out = nxt
    return sorted(out, key=lambda i: (i.entity, i.start))


def hand_over_spans(
    spans: Mapping[Entity, Sequence[tuple[date, date]]], changes: Sequence[IsinChange]
) -> dict[Entity, list[tuple[date, date]]]:
    """The same cut for blocked spans: a span belongs to the instrument that trades then."""
    out = {e: list(v) for e, v in spans.items()}
    for src, tgt, eff in changes:
        a, b = f"i:{src}", f"i:{tgt}"
        pooled = out.pop(a, []) + out.pop(b, [])
        before = [(lo, min(hi, eff)) for lo, hi in pooled if lo < eff]
        after = [(max(lo, eff), hi) for lo, hi in pooled if hi > eff]
        if before:
            out[a] = sorted(before)
        if after:
            out[b] = sorted(after)
    return out


def state_on(walk: Walk, comps: Sequence[str], day: date) -> Members:
    cur = _union(walk.initial, comps)
    for s in walk.steps:
        if s.day <= day:
            cur = _union(s.after, comps)
    return cur


def reconcile(
    walk: Walk, comps: Sequence[str], snapshots: Mapping[date, Members], coverage: str = "FULL",
    same_issuer: Mapping[Entity, Entity] | None = None,
) -> list[dict[str, object]]:  # fmt: skip
    """Compare the reconstructed union with independent snapshots inside the window. `coverage` is
    FULL when the snapshot speaks for the whole union, PARTIAL when it covers only part of it (an
    entity absent from both sides then proves nothing). `same_issuer` maps a superseded ISIN's
    entity to its issuer's latest one, so an ISIN change is not read as a membership disagreement;
    it is applied to BOTH sides for the comparison only and merges no instrument anywhere else."""
    same = same_issuer or {}
    for c in comps:
        if c not in walk.initial:
            raise KeyError(c)
    out: list[dict[str, object]] = []
    for d in sorted(snapshots):
        if not walk.start <= d <= walk.anchor_date:
            continue
        rec = frozenset(same.get(e, e) for e in state_on(walk, comps, d))
        snap = frozenset(same.get(e, e) for e in snapshots[d])
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

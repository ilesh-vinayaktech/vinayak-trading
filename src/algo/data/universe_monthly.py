"""Reconcile official month-end SNAPSHOTS with press-release EVENTS, component by component.

For consecutive snapshots k and k+1 of one index: start from k, apply the events whose effective
date falls in (date_k, date_k+1] (a change effective on day D is in the close-of-day snapshot of any
date >= D), and compare with k+1. Whatever differs is a finding, never silently fixed:

  UNEXPLAINED_ADD / UNEXPLAINED_REMOVE   the snapshot changed with no event that explains it
  EVENT_NOT_OBSERVED                      an event's effect is not in the next snapshot
  UNION_MISMATCH                          Nifty 200 snapshot vs its components in the same month
  COUNT_ANOMALY                           a snapshot does not have the index's usual size
  GAP                                     a month with no snapshot (the window spans two months)

Snapshots are month-END evidence: they say nothing about the days between, and no event date is
manufactured from them. Free-float and plain 'Midcap 100' are one index (renamed 2018-04-02); the
Full Midcap 100 is a different index and stays separate."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from algo.data.universe_derive import BOUNDARY

EXPECTED = {
    "NIFTY_50": {50}, "NIFTY_NEXT_50": {50}, "NIFTY_100": {100}, "NIFTY_200": {200},
    "MIDCAP_100": {100}, "MIDCAP_100_FULL": {100},
}  # fmt: skip
CONTEXT_DAYS = 45


def series(component: str) -> str:
    """The Free-float Midcap 100 and Nifty Midcap 100 are one index under two names."""
    return "MIDCAP_100" if component == "MIDCAP_100_FREE_FLOAT" else component


@dataclass(frozen=True)
class Snap:
    component: str
    as_of: date
    members: Mapping[str, str]  # key ("i:<id>" or "s:<SYMBOL>") -> symbol as printed


@dataclass(frozen=True)
class Ev:
    key: str
    symbol: str
    component: str
    action: str  # INCLUDED | EXCLUDED
    effective: date
    doc: str


@dataclass(frozen=True)
class Diff:
    kind: str
    component: str
    start: date | None  # previous snapshot date
    end: date  # snapshot date the finding is about
    key: str
    symbol: str
    detail: str
    context: tuple[str, ...] = ()  # nearby events for this key, to read mid-month changes


def _context(events: Iterable[Ev], key: str, around: date) -> tuple[str, ...]:
    lo, hi = around - timedelta(days=CONTEXT_DAYS), around + timedelta(days=CONTEXT_DAYS)
    return tuple(
        f"{e.effective} {e.component} {e.action} ({e.doc})"
        for e in sorted(events, key=lambda x: x.effective)
        if e.key == key and lo <= e.effective <= hi
    )


def transitions(component: str, snaps: list[Snap], events: list[Ev]) -> list[Diff]:
    """Snapshot k + events in (date_k, date_k+1]  vs  snapshot k+1, for one index."""
    snaps = sorted((s for s in snaps if series(s.component) == component), key=lambda s: s.as_of)
    evs = [e for e in events if series(e.component) == component]
    out: list[Diff] = []
    for prev, cur in zip(snaps, snaps[1:], strict=False):
        window = sorted(
            (e for e in evs if prev.as_of < e.effective <= cur.as_of), key=lambda e: e.effective
        )
        predicted = dict(prev.members)
        last_action: dict[str, str] = {}
        for e in window:
            last_action[e.key] = e.action
            if e.action == "INCLUDED":
                predicted[e.key] = e.symbol
            else:
                predicted.pop(e.key, None)
        names = {**prev.members, **cur.members, **{e.key: e.symbol for e in window}}
        far = " (snapshots >45 days apart)" if (cur.as_of - prev.as_of).days > 45 else ""
        for key in sorted(set(cur.members) ^ set(predicted)):
            in_cur = key in cur.members
            action = last_action.get(key)
            if in_cur and action == "EXCLUDED":
                kind, why = (
                    "EVENT_NOT_OBSERVED",
                    "a removal event is in the window, yet it is still a member",
                )
            elif not in_cur and action == "INCLUDED":
                kind, why = (
                    "EVENT_NOT_OBSERVED",
                    "an inclusion event is in the window, yet it is not a member",
                )
            elif in_cur:
                kind, why = "UNEXPLAINED_ADD", "in the snapshot, but no event adds it"
            else:
                kind, why = (
                    "UNEXPLAINED_REMOVE",
                    "was a member, no event removes it, yet it is gone",
                )
            out.append(Diff(kind, component, prev.as_of, cur.as_of, key, names[key], why + far,
                            _context(evs, key, cur.as_of)))  # fmt: skip
    return out


def union_checks(snaps: list[Snap]) -> list[Diff]:
    """Nifty 200 snapshot against the union of its components in the same month."""
    by_date: dict[date, dict[str, Snap]] = defaultdict(dict)
    for s in snaps:
        by_date[s.as_of][series(s.component)] = s
    out: list[Diff] = []
    for d, comp in sorted(by_date.items()):
        n200 = comp.get("NIFTY_200")
        # Nifty 200 used the Full Midcap 100 until the 2018-04-02 definition change
        mid = comp.get("MIDCAP_100_FULL") if d < BOUNDARY else comp.get("MIDCAP_100")
        parts = [comp.get("NIFTY_50"), comp.get("NIFTY_NEXT_50"), mid]
        if n200 is None or any(p is None for p in parts):
            continue
        union: dict[str, str] = {}
        for p in parts:
            assert p is not None
            union.update(p.members)
        for key in sorted(set(union) - set(n200.members)):
            why = "in the Nifty 50 / Next 50 / Midcap 100 snapshots but not in Nifty 200"
            out.append(Diff("UNION_MISMATCH", "NIFTY_200", None, d, key, union[key], why))
        for key in sorted(set(n200.members) - set(union)):
            why = "in the Nifty 200 snapshot but in none of its three components"
            out.append(Diff("UNION_MISMATCH", "NIFTY_200", None, d, key, n200.members[key], why))
    return out


def count_checks(snaps: list[Snap]) -> list[Diff]:
    out = []
    for s in sorted(snaps, key=lambda x: (x.component, x.as_of)):
        want = EXPECTED.get(series(s.component))
        if want is not None and len(s.members) not in want:
            dvr = sorted(sym for sym in s.members.values() if sym.endswith("DVR"))
            note = f"; includes a second share class: {', '.join(dvr)}" if dvr else ""
            why = f"{len(s.members)} constituents, expected {sorted(want)}{note}"
            out.append(Diff("COUNT_ANOMALY", series(s.component), None, s.as_of, "", "", why))
    return out


def gap_checks(component: str, snaps: list[Snap], start: date, end: date) -> list[Diff]:
    """Month-ends in [start, end] that have no snapshot for this index."""
    have = {(s.as_of.year, s.as_of.month) for s in snaps if series(s.component) == component}
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        if (y, m) not in have:
            out.append(
                Diff("GAP", component, None, date(y, m, 1), "", "", "no snapshot for this month")
            )
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def reconcile(snaps: list[Snap], events: list[Ev]) -> list[Diff]:
    comps = sorted({series(s.component) for s in snaps})
    out: list[Diff] = []
    for c in comps:
        out += transitions(c, snaps, events)
    out += union_checks(snaps) + count_checks(snaps)
    return out


def categorize(diffs: list[Diff]) -> list[tuple[Diff, str]]:
    """A category for every finding, so none is left unexplained or silently accepted:

    METHODOLOGY_BOUNDARY  the month of the 2018-04-02 Midcap 100 definition change
    IDENTITY_SPLIT        one symbol is both added and removed in the same window: the two sources
                          keyed the same stock differently (an identity artefact, not a change)
    PLACEHOLDER           a DUMMY... symbol of a demerged entity
    SHARE_CLASS           a second share class (DVR)
    EVIDENCE_GAP          nothing explains it: a release is missing, unread or wrongly parsed
    """
    both = {
        (d.component, d.end, d.symbol)
        for d in diffs
        if d.kind == "UNEXPLAINED_ADD"
        and any(o.kind == "UNEXPLAINED_REMOVE" and (o.component, o.end, o.symbol)
                == (d.component, d.end, d.symbol) for o in diffs)
    }  # fmt: skip
    out = []
    for d in diffs:
        if d.kind in ("UNEXPLAINED_ADD", "UNEXPLAINED_REMOVE", "EVENT_NOT_OBSERVED"):
            if (d.end.year, d.end.month) == (BOUNDARY.year, BOUNDARY.month):
                cat = "METHODOLOGY_BOUNDARY"
            elif (d.component, d.end, d.symbol) in both:
                cat = "IDENTITY_SPLIT"
            elif d.symbol.startswith("DUMMY"):
                cat = "PLACEHOLDER"
            elif d.symbol.endswith("DVR"):
                cat = "SHARE_CLASS"
            else:
                cat = "EVIDENCE_GAP"
        elif d.kind == "COUNT_ANOMALY":
            cat = "SHARE_CLASS" if "second share class" in d.detail else "EVIDENCE_GAP"
        else:
            cat = d.kind
        out.append((d, cat))
    return out


@dataclass(frozen=True)
class Span:
    start: date  # first snapshot of a run
    end: date  # last snapshot of the run
    months: int


@dataclass(frozen=True)
class Coverage:
    component: str
    first: date
    last: date
    snapshots: int
    transitions: int
    clean: int
    confirmed: tuple[Span, ...]  # runs of consecutive snapshots whose every transition reconciles
    unconfirmed: tuple[date, ...]  # snapshot dates whose incoming transition does not reconcile


UNCONFIRMING = ("UNEXPLAINED_ADD", "UNEXPLAINED_REMOVE", "EVENT_NOT_OBSERVED")


def coverage(snaps: list[Snap], categorized: list[tuple[Diff, str]]) -> list[Coverage]:
    """Per index, the date ranges that are CONFIRMED (every monthly transition agrees with the
    press-release events, or differs only by an explained placeholder/share-class artefact) and the
    snapshot dates that are not. Everything else must be treated as unresolved by strict mode."""
    bad: dict[str, set[date]] = defaultdict(set)
    for d, cat in categorized:
        if d.kind in UNCONFIRMING and cat not in ("PLACEHOLDER", "SHARE_CLASS"):
            bad[d.component].add(d.end)
    out = []
    for comp in sorted({series(s.component) for s in snaps}):
        dates = sorted(s.as_of for s in snaps if series(s.component) == comp)
        runs: list[list[date]] = [[dates[0]]]
        unconfirmed = []
        for prev, cur in zip(dates, dates[1:], strict=False):
            if cur in bad[comp] or (cur - prev).days > 45:
                unconfirmed.append(cur)
                runs.append([cur])
            else:
                runs[-1].append(cur)
        spans = tuple(Span(r[0], r[-1], len(r)) for r in runs if len(r) > 1)
        transitions = len(dates) - 1
        out.append(Coverage(comp, dates[0], dates[-1], len(dates), transitions,
                            transitions - len(unconfirmed), spans, tuple(unconfirmed)))  # fmt: skip
    return out

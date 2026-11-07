"""Derive Nifty 200 membership from the parsed component-index events, and say honestly where the
evidence does not hold together. Nothing is forced to 200 members.

  Nifty 200 = Nifty 50 + Nifty Next 50 + Nifty Midcap 100 (union: transfers between components
  net out). The Midcap 100 definition changed on 2018-04-02 (Full -> Free-float, renamed), so two
  separate methodology series are derived and never merged:
      NIFTY200_M1  events effective before the boundary, midcap = Full Midcap 100
      NIFTY200     events effective on/after it,         midcap = Midcap 100

Checks (each failure is a Discrepancy, not an error):
  forward     events must alternate ADD/REMOVE per instrument
  snapshot    the state after the last event must equal the current official Nifty 200 snapshot
  checkpoint  every explicit 'NIFTY 200' row in the releases must be reproduced by the union
  count       member count reconstructed backwards from the snapshot at each change date
Announcement and effective dates are kept apart on every derived event."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

BOUNDARY = date(2018, 4, 2)  # Midcap 100 methodology change (NSE press release 2018-01-05)
M1, M2 = "NIFTY200_M1", "NIFTY200"
UNION = {
    M1: frozenset({"NIFTY_50", "NIFTY_NEXT_50", "MIDCAP_100_FULL"}),
    # from the boundary the Free-float Midcap 100 IS Nifty Midcap 100 (renamed): both labels count
    M2: frozenset({"NIFTY_50", "NIFTY_NEXT_50", "MIDCAP_100", "MIDCAP_100_FREE_FLOAT"}),
}


@dataclass(frozen=True)
class CEvent:
    key: str  # "i:<instrument_id>" when mapped, else "s:<SYMBOL>"
    symbol: str
    component: str
    action: str  # INCLUDED | EXCLUDED
    effective: date
    announced: date
    doc_id: str
    page: int
    placeholder: bool = False


@dataclass(frozen=True)
class Derived:
    index_id: str
    key: str
    symbol: str
    event_type: str  # ADD | REMOVE
    effective: date
    announced: date
    docs: tuple[str, ...]
    placeholder: bool


@dataclass(frozen=True)
class Discrepancy:
    kind: str
    key: str
    symbol: str
    on: date | None
    detail: str


@dataclass
class Report:
    derived: list[Derived] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    counts: dict[str, list[tuple[date, int]]] = field(default_factory=dict)  # per series
    gaps: dict[str, int] = field(default_factory=dict)

    def of_kind(self, kind: str) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.kind == kind]


def series_of(effective: date) -> str:
    return M1 if effective < BOUNDARY else M2


def derive_union(events: Iterable[CEvent]) -> tuple[list[Derived], list[Discrepancy]]:
    """Union membership changes per series, plus component-level anomalies. A component's prior
    state is inferred from the first event seen for it (EXCLUDED => it was a member, INCLUDED =>
    it was not); an INCLUDED while already a member (or EXCLUDED while not) means an event between
    them is missing."""
    by: dict[tuple[str, str], list[CEvent]] = defaultdict(list)
    for e in events:
        sid = series_of(e.effective)
        if e.component in UNION[sid]:
            by[(sid, e.key)].append(e)
    out: list[Derived] = []
    anomalies: list[Discrepancy] = []
    for (sid, key), evs in sorted(by.items()):
        evs.sort(key=lambda e: (e.effective, e.component))
        state: dict[str, bool] = {}
        for e in evs:
            state.setdefault(e.component, e.action == "EXCLUDED")
        seen_before: set[str] = set()
        for day in sorted({e.effective for e in evs}):
            before = any(state.values())
            todays = [e for e in evs if e.effective == day]
            for e in todays:
                wants = e.action == "INCLUDED"
                if e.component in seen_before and state[e.component] == wants:
                    why = f"{e.component} {e.action} twice in a row: an event between is missing"
                    anomalies.append(Discrepancy("NON_ALTERNATING", key, e.symbol, day, why))
                state[e.component] = wants
                seen_before.add(e.component)
            after = any(state.values())
            if before != after:
                out.append(Derived(
                    sid, key, todays[0].symbol, "ADD" if after else "REMOVE", day,
                    min(e.announced for e in todays), tuple(sorted({e.doc_id for e in todays})),
                    any(e.placeholder for e in todays),
                ))  # fmt: skip
    return sorted(out, key=lambda d: (d.index_id, d.effective, d.key)), anomalies


def check_snapshot(derived: list[Derived], snapshot: set[int]) -> list[Discrepancy]:
    """Latest series only: final state per instrument vs the current official list."""
    final: dict[str, Derived] = {}
    for d in derived:
        if d.index_id == M2:
            final[d.key] = d
    out = []
    for key, d in sorted(final.items()):
        if d.placeholder or not key.startswith("i:"):
            continue
        member_now = int(key[2:]) in snapshot
        expect = d.event_type == "ADD"
        if member_now != expect:
            now = "member" if member_now else "not a member"
            why = f"last event is {d.event_type} but the current snapshot says {now}"
            out.append(Discrepancy("SNAPSHOT_MISMATCH", key, d.symbol, d.effective, why))
    return out


def check_checkpoints(derived: list[Derived], explicit: Iterable[CEvent]) -> list[Discrepancy]:
    """Explicit 'NIFTY 200' rows are independent evidence: the union must reproduce them."""
    have = {(d.key, d.effective, d.event_type) for d in derived}
    explicit = list(explicit)
    want = {(e.key, e.effective, "ADD" if e.action == "INCLUDED" else "REMOVE") for e in explicit}
    days = {e.effective for e in explicit}
    name = {e.key: e.symbol for e in explicit}
    out = []
    for key, eff, typ in sorted(want - have):
        why = f"explicit Nifty 200 {typ} not produced by the component union"
        out.append(Discrepancy("CHECKPOINT_MISSING", key, name[key], eff, why))
    for d in derived:
        if d.effective in days and (d.key, d.effective, d.event_type) not in want:
            why = f"union derives {d.event_type} that no explicit Nifty 200 row lists"
            out.append(Discrepancy("CHECKPOINT_EXTRA", d.key, d.symbol, d.effective, why))
    return out


def backward_counts(derived: list[Derived], snapshot: set[int]) -> list[tuple[date, int]]:
    """Mapped-instrument member count just BEFORE each change date, walking back from the current
    official list (M2 series). Unmapped/placeholder members are absent, so a deficit is expected and
    reported, not hidden."""
    state = set(snapshot)
    by_day: dict[date, list[Derived]] = defaultdict(list)
    for d in derived:
        if d.index_id == M2 and d.key.startswith("i:"):
            by_day[d.effective].append(d)
    series = []
    for day in sorted(by_day, reverse=True):
        for d in by_day[day]:
            iid = int(d.key[2:])
            if d.event_type == "ADD":
                state.discard(iid)
            else:
                state.add(iid)
        series.append((day, len(state)))  # members just before `day`, all its changes undone
    return sorted(series)


def build_report(
    component_events: list[CEvent], snapshot: set[int], manual_documents: Iterable[str] = (),
    undated_rows: Iterable[tuple[str, str, str, str]] = (),
) -> Report:  # fmt: skip
    rep = Report()
    rep.derived, anomalies = derive_union(component_events)
    rep.discrepancies += anomalies
    rep.discrepancies += check_snapshot(rep.derived, snapshot)
    explicit = [e for e in component_events if e.component == "NIFTY_200"]
    rep.discrepancies += check_checkpoints(rep.derived, explicit)
    rep.counts[M2] = backward_counts(rep.derived, snapshot)
    for e in component_events:
        if e.key.startswith("s:"):
            kind = "PLACEHOLDER_EVENT" if e.placeholder else "UNMAPPED_EVENT"
            why = f"{e.component} {e.action} cannot be tied to an instrument"
            rep.discrepancies.append(Discrepancy(kind, e.key, e.symbol, e.effective, why))
    for doc in manual_documents:
        why = "release not parsed: any change in it is missing"
        rep.discrepancies.append(Discrepancy("MANUAL_DOCUMENT", "", doc, None, why))
    for symbol, component, action, doc in undated_rows:
        why = f"{component} {action} in {doc} has no effective date: it cannot be placed in time"
        rep.discrepancies.append(Discrepancy("UNDATED_ROW", "", symbol, None, why))
    why = "Midcap 100 definition changed (Full -> Free-float); the two series are not joined"
    rep.discrepancies.append(Discrepancy("METHODOLOGY_BOUNDARY", "", "", BOUNDARY, why))
    rep.gaps = dict(sorted(_tally(rep.discrepancies).items()))
    return rep


def _tally(ds: Iterable[Discrepancy]) -> Mapping[str, int]:
    out: dict[str, int] = defaultdict(int)
    for d in ds:
        out[d.kind] += 1
    return out

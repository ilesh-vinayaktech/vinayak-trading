"""Issuer-level price history across an ISIN change, WITHOUT merging tradable instruments.

Invariant: the same ISSUER is not the same INSTRUMENT. After a SAME_ISSUER_ISIN_CHANGE the old and
the new ISIN are two instruments; each owns only the observations from its own interval.
Instrument-scoped reads (`BarReader.history`) return exactly one instrument's own bars (execution,
audit). Issuer-scoped reads (`BarReader.issuer_history`) stitch the chain for signals and charts and
keep who owned each bar. They refuse to guess when the data does not match the proposed identity:
a bar dated outside its owner's interval, or two owners for one session."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from algo.data.adjust.factors import ActionRecord

IST = ZoneInfo("Asia/Kolkata")
Row = tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]


class IdentityError(Exception):
    pass


@dataclass(frozen=True)
class Link:
    """A SAME_ISSUER_ISIN_CHANGE: `source` owns the history before `effective`, `target` from it."""

    source: int
    target: int
    effective: date


@dataclass(frozen=True)
class Segment:
    instrument_id: int
    start: date | None  # first session this instrument owns (None: since its beginning)
    end: date | None  # first session it NO LONGER owns (None: until now); end-exclusive


def chain(links: Sequence[Link], instrument_id: int) -> list[Segment]:
    """The issuer chain containing `instrument_id`, oldest first. No link: the instrument alone."""
    nxt: dict[int, Link] = {}
    prev: dict[int, Link] = {}
    for k in links:
        if k.source in nxt or k.target in prev or k.source == k.target:
            raise IdentityError(f"ambiguous ISIN-change links around instrument {k.source}")
        nxt[k.source], prev[k.target] = k, k
    head, seen = instrument_id, {instrument_id}
    while head in prev:
        head = prev[head].source
        if head in seen:
            raise IdentityError("ISIN-change links form a cycle")
        seen.add(head)
    out: list[Segment] = []
    start: date | None = None
    cur = head
    while cur in nxt:
        k = nxt[cur]
        out.append(Segment(cur, start, k.effective))
        start, cur = k.effective, k.target
    out.append(Segment(cur, start, None))
    return out


def latest_of(links: Sequence[Link]) -> dict[int, int]:
    """Each superseded ISIN -> the latest ISIN of its issuer chain. For COMPARING membership across
    an ISIN change only (is this the same issuer?); it never makes the two instruments one."""
    return {
        seg.instrument_id: chain(links, seg.instrument_id)[-1].instrument_id
        for k in links
        for seg in chain(links, k.source)
        if seg.end is not None
    }


def _day(row: Row) -> date:
    return row[0].astimezone(IST).date()


def stitch(
    segments: Sequence[Segment],
    rows: Mapping[int, Sequence[Row]],
    recs: Mapping[int, Sequence[ActionRecord]],
) -> tuple[list[Row], list[int], list[ActionRecord]]:
    """(bars oldest first, the owning instrument of each bar, deduplicated corporate actions).
    A single segment is a plain pass-through. With several, every bar must lie inside its owner's
    interval: a bar outside it means the data has not been moved to the proposed identity, and
    silently dropping or keeping it would pick an owner by guesswork."""
    if len(segments) == 1:
        only = segments[0].instrument_id
        return list(rows[only]), [only] * len(rows[only]), list(recs[only])
    stitched: list[tuple[Row, int]] = []
    for seg in segments:
        for r in rows[seg.instrument_id]:
            d = _day(r)
            if (seg.start is not None and d < seg.start) or (seg.end is not None and d >= seg.end):
                raise IdentityError(
                    f"instrument {seg.instrument_id} holds a bar dated {d}, outside its interval "
                    f"[{seg.start}, {seg.end}): the data does not match the ISIN-change identity"
                )
            stitched.append((r, seg.instrument_id))
    stitched.sort(key=lambda p: p[0][0])
    stamps = [p[0][0] for p in stitched]
    if len(set(stamps)) != len(stamps):
        raise IdentityError("two instruments of one issuer own the same session")
    unique: dict[tuple[object, ...], ActionRecord] = {}
    for seg in segments:
        for a in recs[seg.instrument_id]:
            unique.setdefault((a.ex_date, a.kind, a.status, a.num, a.den, a.amount), a)
    return (
        [p[0] for p in stitched],
        [p[1] for p in stitched],
        sorted(unique.values(), key=lambda a: (a.ex_date, a.kind)),
    )

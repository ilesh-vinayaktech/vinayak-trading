# ruff: noqa: E501
"""The stocks a study may trade on each day: members of the chosen market-cap segments by AMFI's list in force that day.

Each AMFI list (algo.data.market_caps) applies from its effective date until the next list takes over, so a stock is a member
only while the list in force puts it in a chosen segment, and only once we hold at least `min_history_sessions` of Kite
history for it (the study prices everything from the frozen Kite history). Before the first list is relied on (2018-08-01)
the owner chose: leave those days out, or rank stocks by trailing traded value in the same rank bands as a stand-in.
The returned coverage says, per list, how many companies the segments held, how many matched one of our instruments and how
many we hold Kite history for: the gap between the first and last is stocks that no longer exist or never traded on Kite
(delisted or merged since), which is survivorship the owner should see rather than have hidden."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import psycopg

from algo.data.amfi_caps import segment_of
from algo.data.universe import Interval
from algo.research.study import UniverseSpec
from algo.strategies.nifty200_momentum import IntervalMembership

STAND_IN = "traded value (stand-in)"
RANK_SESSIONS = 126  # about six months of trading for the stand-in's average traded value
MIN_RANKED_SESSIONS = 60  # a stock needs this much trading before the boundary to be ranked at all


def _eligible_from(conn: psycopg.Connection, sessions: int) -> dict[int, date]:
    """The first day each stock has `sessions` days of Kite history (the day with that many bars up to and including it)."""
    rows = conn.execute(
        "SELECT instrument_id, (array_agg(day ORDER BY day))[%s] FROM ("
        "  SELECT instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date AS day FROM bar_1d WHERE source='kite' GROUP BY 1, 2"
        ") d GROUP BY instrument_id HAVING count(*) >= %s",
        (max(sessions, 1), max(sessions, 1)),
    ).fetchall()
    return {int(i): d for i, d in rows}


def _amfi_periods(conn: psycopg.Connection) -> list[tuple[str, date, date | None, dict[int, str]]]:
    """(list label, in force from, in force until (exclusive), instrument -> segment), earliest first."""
    heads = conn.execute(
        "SELECT period_end, effective_from FROM market_cap_list ORDER BY effective_from"
    ).fetchall()
    out: list[tuple[str, date, date | None, dict[int, str]]] = []
    for k, (period_end, eff) in enumerate(heads):
        nxt = heads[k + 1][1] if k + 1 < len(heads) else None
        segs = {
            int(i): s
            for i, s in conn.execute(
                "SELECT instrument_id, segment FROM market_cap_rank WHERE period_end=%s AND instrument_id IS NOT NULL",
                (period_end,),
            )
        }
        out.append((period_end.isoformat(), eff, nxt, segs))
    return out


def _traded_value_segments(conn: psycopg.Connection, boundary: date) -> dict[int, str]:
    """Rank stocks by average daily traded value over the sessions before `boundary`; the AMFI rank bands name the segment."""
    rows = conn.execute(
        "SELECT instrument_id FROM ("
        "  SELECT instrument_id, close * volume AS v, row_number() OVER (PARTITION BY instrument_id ORDER BY ts DESC) AS rn"
        "  FROM bar_1d WHERE source='kite' AND ts < %s::date AND ts >= (%s::date - 260)"
        ") r WHERE rn <= %s GROUP BY instrument_id HAVING count(*) >= %s ORDER BY avg(v) DESC, instrument_id",
        (boundary, boundary, RANK_SESSIONS, MIN_RANKED_SESSIONS),
    ).fetchall()
    return {int(r[0]): segment_of(rank) for rank, r in enumerate(rows, 1)}


def _half_year_starts(start: date, before: date) -> list[date]:
    """Feb 1 and Aug 1 boundaries from the one at or before `start` up to `before` (exclusive): the stand-in's re-rank dates."""
    bounds = [
        b
        for y in range(start.year - 1, before.year + 1)
        for m in (2, 8)
        if (b := date(y, m, 1)) < before
    ]
    first = max(b for b in bounds if b <= start)
    return [b for b in bounds if b >= first]


def build(
    conn: psycopg.Connection, spec: UniverseSpec, start: date, end: date
) -> tuple[IntervalMembership, list[dict[str, Any]]]:
    """Members of `spec.segments` on every day of [start, end], and the per-list coverage report."""
    wanted = set(spec.segments)
    eligible = _eligible_from(conn, spec.min_history_sessions)
    limit = end + timedelta(days=1)  # intervals are half-open
    periods = _amfi_periods(conn)
    first_effective = periods[0][1] if periods else limit
    intervals: list[Interval] = []
    coverage: list[dict[str, Any]] = []

    def add(
        label: str, lo: date, hi: date | None, segs: dict[int, str], in_segments: int | None = None
    ) -> None:
        a, b = max(lo, start), min(hi, limit) if hi else limit
        if a >= b:
            return
        chosen = [i for i, s in segs.items() if s in wanted]
        usable = [i for i in chosen if i in eligible]
        for i in usable:
            lo_i = max(a, eligible[i])
            if lo_i < b:
                intervals.append(Interval(i, lo_i, b))
        coverage.append({"list": label, "from": a.isoformat(), "until": (b - timedelta(days=1)).isoformat(),
                         "in_segments": len(chosen) if in_segments is None else in_segments, "matched": len(chosen), "usable": len(usable)})  # fmt: skip

    if start < first_effective and spec.before_segment_lists == "traded_value_rank":
        bounds = _half_year_starts(start, min(first_effective, limit))
        for k, b in enumerate(bounds):
            add(
                STAND_IN,
                b,
                bounds[k + 1] if k + 1 < len(bounds) else first_effective,
                _traded_value_segments(conn, b),
            )
    for label, eff, nxt, segs in periods:
        if eff >= limit or (nxt is not None and nxt <= start):
            continue
        in_seg = conn.execute(
            "SELECT count(*) FROM market_cap_rank WHERE period_end=%s AND segment = ANY(%s)",
            (label, list(wanted)),
        ).fetchone()
        add(label, eff, nxt, segs, in_segments=int(in_seg[0]) if in_seg else 0)
    return IntervalMembership(intervals), coverage

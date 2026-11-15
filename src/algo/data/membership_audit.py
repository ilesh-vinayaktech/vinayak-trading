# ruff: noqa: E501
"""Audit the STORED membership of an index over a list of sessions: who was a member, could that have been known then, is each member an
instrument, and does each instrument have a bar that day. Membership, instrument and price are separate questions; this reports each."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg

from algo.data.universe import UniverseGap, constituents_on

BY_DESIGN = frozenset(
    {"s:JIOFIN"}
)  # the pre-listing Jio entity: NSE's zero-price stand-in (see membership_entity_equivalence.csv); placeholders are 'p:'
Span = tuple[date, date, int]  # first session, last session, number of sessions


@dataclass
class Audit:
    sessions: int = 0
    unverified: int = (
        0  # sessions outside VERIFIED coverage or with unverified events: no strict answer exists
    )
    retrospective: int = (
        0  # sessions whose actual members differ from the members knowable that day
    )
    by_design: dict[str, Span] = field(
        default_factory=dict
    )  # zero-price index placeholders: members, not investable, by NSE design
    untradable: dict[str, Span] = field(
        default_factory=dict
    )  # members with no instrument that are NOT placeholders
    missing_bars: dict[int, Span] = field(
        default_factory=dict
    )  # instruments that were members on a session with no daily bar


def _add(spans: dict[Any, Span], key: Any, day: date) -> None:
    lo, _, n = spans.get(key, (day, day, 0))
    spans[key] = (lo, day, n + 1)


def audit(conn: psycopg.Connection, index_id: str, sessions: list[date]) -> Audit:
    out = Audit(sessions=len(sessions))
    actual: dict[date, set[str]] = {}
    for d in sessions:
        try:
            actual[d] = constituents_on(conn, index_id, d, strict=False, historical=True)
            known = constituents_on(conn, index_id, d, strict=True)
        except (
            UniverseGap
        ):  # outside declared or verified coverage: there is no answer, and none is guessed
            out.unverified += 1
            actual.setdefault(d, set())
        else:
            out.retrospective += known != actual[d]
    ids = sorted({int(k[2:]) for ks in actual.values() for k in ks if k.startswith("i:")})
    have = (
        set(
            conn.execute(
                "SELECT DISTINCT instrument_id, ts::date FROM bar_1d WHERE instrument_id = ANY(%s) AND ts::date BETWEEN %s AND %s",
                (ids, min(sessions), max(sessions)),
            ).fetchall()
        )
        if sessions
        else set()
    )
    for d in sessions:
        for k in sorted(actual[d]):
            if k.startswith("i:"):
                if (int(k[2:]), d) not in have:
                    _add(out.missing_bars, int(k[2:]), d)
            elif k.startswith("p:") or k in BY_DESIGN:
                _add(out.by_design, k, d)
            else:
                _add(out.untradable, k, d)
    return out

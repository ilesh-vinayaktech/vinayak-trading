# ruff: noqa: E501
"""NSE's holiday list -> the live trading calendar (market_session).

Every upcoming exchange holiday becomes a CLOSED day. Starred entries (Muhurat and other special sessions whose hours
NSE announces later) keep their star in the note, and are reported as needing their hours entered by a person: nothing is
guessed. Past dates are left alone, a repeat sync changes nothing, and sessions entered by hand are never touched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from algo.data.providers.nse_holidays import parse_holidays
from algo.live.market_calendar import mark_closed


@dataclass(frozen=True)
class SyncResult:
    closed: int  # upcoming days now marked closed
    needs_times: list[date]  # starred days still without hours


def sync_holidays(
    conn: psycopg.Connection, raw: bytes, *, today: date, now: datetime
) -> SyncResult:
    found = parse_holidays(raw)
    special = dict(found.special_review)
    days = {d: found.names[d] for d in found.weekday_holidays} | special
    upcoming = sorted(d for d in days if d >= today)
    for d in upcoming:
        mark_closed(conn, day=d, note=days[d], source="nse", actor=None, now=now)
    needs = [
        d
        for d in sorted(special)
        if d >= today
        and conn.execute(
            "SELECT 1 FROM market_session WHERE session_date=%s AND kind='SESSION'", (d,)
        ).fetchone()
        is None
    ]
    return SyncResult(len(upcoming), needs)

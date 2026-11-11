# ruff: noqa: E501
"""When the exchange trades, as the live feed and the portal need it (table market_session, migration 034).

A date's windows: the SESSION entries it has, if any (they replace everything else, so a Muhurat evening works even
though NSE lists that day as a holiday); otherwise nothing if it is marked CLOSED; otherwise the regular Mon-Fri
09:15-15:30 IST session; otherwise nothing (a weekend). Entries are wall-clock IST; windows come out as UTC instants."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

IST = ZoneInfo("Asia/Kolkata")
REGULAR = (time(9, 15), time(15, 30))
Window = tuple[datetime, datetime]


class CalendarError(ValueError):
    pass


def _utc(day: date, t: time) -> datetime:
    return datetime.combine(day, t, IST).astimezone(UTC)


def windows_for(conn: psycopg.Connection, day: date) -> list[Window]:
    rows = conn.execute(
        "SELECT kind, start_time, end_time FROM market_session WHERE session_date=%s ORDER BY start_time",
        (day,),
    ).fetchall()
    sessions = [(_utc(day, s), _utc(day, e)) for k, s, e in rows if k == "SESSION"]
    if sessions:
        return sessions
    if rows or day.weekday() >= 5:  # only CLOSED rows can be left, or a weekend
        return []
    return [(_utc(day, REGULAR[0]), _utc(day, REGULAR[1]))]


def add_session(
    conn: psycopg.Connection,
    *,
    day: date,
    start: time,
    end: time,
    note: str,
    source: str,
    actor: UUID | None,
    now: datetime,
) -> int:
    if start >= end:
        raise CalendarError("a session needs start before end")
    clash = conn.execute(
        "SELECT 1 FROM market_session WHERE session_date=%s AND kind='SESSION' AND start_time < %s AND end_time > %s",
        (day, end, start),
    ).fetchone()
    if clash:
        raise CalendarError("that window overlaps another session on the same day")
    row = conn.execute(
        "INSERT INTO market_session (session_date, kind, start_time, end_time, note, source, created_by, created_at)"
        " VALUES (%s,'SESSION',%s,%s,%s,%s,%s,%s) RETURNING session_id",
        (day, start, end, note.strip(), source, actor, now),
    ).fetchone()
    assert row is not None
    return int(row[0])


def mark_closed(
    conn: psycopg.Connection,
    *,
    day: date,
    note: str,
    source: str,
    actor: UUID | None,
    now: datetime,
) -> int:
    row = conn.execute(
        "INSERT INTO market_session (session_date, kind, note, source, created_by, created_at) VALUES (%s,'CLOSED',%s,%s,%s,%s)"
        " ON CONFLICT (session_date) WHERE kind='CLOSED' DO UPDATE SET note=EXCLUDED.note RETURNING session_id",
        (day, note.strip(), source, actor, now),
    ).fetchone()
    assert row is not None
    return int(row[0])


def remove(conn: psycopg.Connection, session_id: int) -> None:
    if (
        conn.execute(
            "DELETE FROM market_session WHERE session_id=%s RETURNING 1", (session_id,)
        ).fetchone()
        is None
    ):
        raise CalendarError("no such entry")


def list_exceptions(conn: psycopg.Connection, from_day: date, to_day: date) -> list[dict[str, Any]]:
    """Entries with from_day <= date < to_day, in date and time order. `needs_times`: NSE lists the day with a star
    (a special session whose hours are announced later) and nobody has entered the hours yet."""
    rows = conn.execute(
        "SELECT m.session_id, m.session_date, m.kind, m.start_time, m.end_time, m.note, m.source,"
        " (m.kind = 'CLOSED' AND m.source = 'nse' AND m.note LIKE '%%*' AND NOT EXISTS"
        "   (SELECT 1 FROM market_session s WHERE s.session_date = m.session_date AND s.kind = 'SESSION'))"
        " FROM market_session m WHERE m.session_date >= %s AND m.session_date < %s"
        " ORDER BY m.session_date, m.start_time NULLS FIRST",
        (from_day, to_day),
    ).fetchall()
    keys = ("id", "day", "kind", "start", "end", "note", "source", "needs_times")
    return [dict(zip(keys, r, strict=True)) for r in rows]

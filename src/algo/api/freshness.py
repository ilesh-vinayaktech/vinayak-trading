"""Is the newest bar current? Judged by sessions, never by calendar-day subtraction: on a Sunday the
Friday bar is current, and a bar is only expected once its file is normally published (18:30 IST).
Holidays are only those the platform has learned (days the exchange published no file); a FUTURE
holiday is unknown, and the result says so."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
PUBLISH_AFTER = time(18, 30)
BASIS = (
    "sessions are weekdays minus the exchange holidays learned from days with no published file; "
    "future holidays are unknown; a session's file is expected after 18:30 IST"
)


def _is_session(d: date, holidays: frozenset[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def assess(last_bar: date, now: datetime, holidays: frozenset[date]) -> dict[str, Any]:
    local = now.astimezone(IST)
    d = local.date()
    expected = d if local.time() >= PUBLISH_AFTER else d - timedelta(days=1)
    while not _is_session(expected, holidays):
        expected -= timedelta(days=1)
    upcoming = expected + timedelta(days=1)
    while not _is_session(upcoming, holidays):
        upcoming += timedelta(days=1)
    behind, x = 0, last_bar
    while x < expected:
        x += timedelta(days=1)
        behind += _is_session(x, holidays)
    return {
        "latest_bar_session": last_bar.isoformat(),
        "expected_latest_session": expected.isoformat(),
        "next_session": upcoming.isoformat(),
        "sessions_behind": behind,
        "status": "CURRENT" if behind == 0 else "BEHIND",
        "basis": BASIS,
    }

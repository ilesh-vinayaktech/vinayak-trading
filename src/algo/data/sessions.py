"""Exchange sessions that a Monday-Friday-minus-holidays rule cannot express (Budget-day and
other weekend sessions, Muhurat). They are DATA with their evidence, kept in
config/exchange_sessions.json, and fed to the calendar. Nothing is invented: a session is listed
only where there is evidence that the exchange traded, and what is NOT known (its kind, its hours)
is stated on the entry."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, time
from pathlib import Path
from typing import Any

from algo.core.calendar import SessionCalendar, nse

REGULAR_HOURS = (time(9, 15), time(15, 30))


def weekend_sessions(days: Iterable[date]) -> list[date]:
    """Dates of a series on a Saturday or Sunday: the exchange traded on a weekend."""
    return sorted(d for d in set(days) if d.weekday() >= 5)


def build_entries(days: Iterable[date], evidence: str, evidence_hash: str) -> list[dict[str, Any]]:
    out = []
    for d in weekend_sessions(days):
        out.append({
            "date": str(d), "weekday": d.strftime("%A"), "kind": "SPECIAL",
            "kind_status": "UNCONFIRMED (weekend: Budget day, Muhurat or an exchange drill)",
            "hours": None, "hours_status": "UNKNOWN (regular hours assumed for bar visibility)",
            "evidence": evidence, "evidence_sha256": evidence_hash,
        })  # fmt: skip
    return out


def load(path: Path) -> tuple[dict[date, tuple[time, time]], dict[date, str]]:
    """(special session hours, special kinds) from the evidence file."""
    doc = json.loads(path.read_text())
    hours: dict[date, tuple[time, time]] = {}
    kinds: dict[date, str] = {}
    for s in doc["sessions"]:
        d = date.fromisoformat(s["date"])
        if s["kind"] not in ("SPECIAL", "MUHURAT"):
            raise ValueError(f"{s['date']}: kind must be SPECIAL or MUHURAT")
        if d in hours:
            raise ValueError(f"{s['date']}: listed twice")
        h = s.get("hours")
        hours[d] = (time.fromisoformat(h[0]), time.fromisoformat(h[1])) if h else REGULAR_HOURS
        kinds[d] = s["kind"]
    return hours, kinds


def calendar(path: Path, holidays: Iterable[date] = ()) -> SessionCalendar:
    hours, kinds = load(path)
    return nse(holidays, hours, kinds)

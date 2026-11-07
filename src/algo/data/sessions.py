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


def _status(text: str, allowed: tuple[str, ...], what: str, d: str) -> str:
    word = text.split(" ", 1)[0]
    if word not in allowed:
        raise ValueError(f"{d}: {what} must start with one of {allowed}, got {text!r}")
    return word


def load(
    path: Path,
) -> tuple[dict[date, tuple[time, time]], dict[date, str], dict[date, tuple[str, str]]]:
    """(hours used for bars, kinds, (kind_status, hours_status)) from the evidence file. Hours given
    without a VERIFIED status, or VERIFIED without hours, are refused: provisional hours must never
    pass as verified."""
    doc = json.loads(path.read_text())
    hours: dict[date, tuple[time, time]] = {}
    kinds: dict[date, str] = {}
    status: dict[date, tuple[str, str]] = {}
    for s in doc["sessions"]:
        d = date.fromisoformat(s["date"])
        if s["kind"] not in ("SPECIAL", "MUHURAT"):
            raise ValueError(f"{s['date']}: kind must be SPECIAL or MUHURAT")
        if d in hours:
            raise ValueError(f"{s['date']}: listed twice")
        ks = _status(s["kind_status"], ("CONFIRMED", "UNCONFIRMED"), "kind_status", s["date"])
        hs = _status(s["hours_status"], ("VERIFIED", "UNKNOWN"), "hours_status", s["date"])
        h = s.get("hours")
        if bool(h) != (hs == "VERIFIED"):
            raise ValueError(f"{s['date']}: hours are given exactly when hours_status is VERIFIED")
        hours[d] = (time.fromisoformat(h[0]), time.fromisoformat(h[1])) if h else REGULAR_HOURS
        kinds[d] = s["kind"]
        status[d] = (ks, hs)
    return hours, kinds, status


def calendar(path: Path, holidays: Iterable[date] = ()) -> SessionCalendar:
    hours, kinds, status = load(path)
    return nse(holidays, hours, kinds, status)

# ruff: noqa: E501
"""The platform state log in the database, and the question every trading entry point asks: may I trade now?"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg

from algo.live.market_calendar import IST
from algo.platform_state.machine import TRADING, PlatformState, State, StateEvent


def latest(conn: psycopg.Connection) -> tuple[State, datetime, str] | None:
    """(state, when, reason) of the last recorded transition."""
    row = conn.execute(
        "SELECT to_state, ts, reason FROM platform_state_event ORDER BY event_id DESC LIMIT 1"
    ).fetchone()
    return None if row is None else (State(row[0]), row[1], row[2])


def append(
    conn: psycopg.Connection, events: Sequence[StateEvent], *, operator: bool = False
) -> None:
    for e in events:
        conn.execute(
            "INSERT INTO platform_state_event (from_state, to_state, reason, operator, ts) VALUES (%s,%s,%s,%s,%s)",
            (e.from_state.value, e.to_state.value, e.reason, operator, e.ts),
        )


def record_halt(conn: psycopg.Connection, now: datetime, reason: str) -> State:
    """Move the platform to HALTED (a kill switch, a reconciliation breach). Leaving it takes an operator."""
    last = latest(conn)
    current = last[0] if last else State.INITIALIZING
    if current is State.HALTED:
        return current
    ps = PlatformState()
    ps.state = current
    ps.transition(State.HALTED, now, reason)
    append(conn, ps.events)
    return State.HALTED


def trading_blocked(conn: psycopg.Connection, now: datetime) -> str | None:
    """Why no strategy may emit targets right now, or None when it may: the last boot must have reached PAPER or LIVE, today."""
    last = latest(conn)
    if last is None:
        return "no platform boot has been recorded (run the platform-boot job)"
    state, when, reason = last
    if state not in TRADING:
        return f"the platform is {state.value}: {reason}"
    booted = when.astimezone(IST).date()
    if booted != now.astimezone(IST).date():
        return f"the last boot was on {booted}: boot again today"
    return None

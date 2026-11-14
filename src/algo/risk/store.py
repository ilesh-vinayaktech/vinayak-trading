# ruff: noqa: E501
"""The kill switch in the database: an append-only log, so the mode in force survives restarts and every change has a who and a why.
Used by the paper path now and by the OMS later. One operator at a time is assumed (no locking between concurrent changes)."""

from __future__ import annotations

from datetime import datetime

import psycopg

from algo.risk.killswitch import KillSwitch, Mode, SwitchEvent


def load(conn: psycopg.Connection) -> KillSwitch:
    rows = conn.execute(
        "SELECT ts, scope, mode, by_who, reason FROM kill_switch_event ORDER BY id"
    ).fetchall()
    return KillSwitch.from_events(
        SwitchEvent(ts, scope, Mode(mode), by, reason) for ts, scope, mode, by, reason in rows
    )


def change(
    conn: psycopg.Connection,
    op: str,
    scope: str | None,
    *,
    by: str,
    reason: str,
    now: datetime,
    emergency_override: bool = False,
) -> KillSwitch:
    """pause | cancel | flatten (needs emergency_override) | resume, for one strategy or (scope None) for all."""
    switch = load(conn)
    before = len(switch.events)
    if op == "flatten":
        switch.flatten(scope, by=by, reason=reason, now=now, emergency_override=emergency_override)
    elif op in ("pause", "cancel", "resume"):
        getattr(switch, op)(scope, by=by, reason=reason, now=now)
    else:
        raise ValueError(f"unknown operation {op!r}")
    save_new(conn, switch, before)
    return switch


def save_new(conn: psycopg.Connection, switch: KillSwitch, already_saved: int) -> None:
    """Write the switch events after the first `already_saved` (what a policy or the reconciler changed in memory)."""
    for e in switch.events[already_saved:]:
        conn.execute(
            "INSERT INTO kill_switch_event (ts, scope, mode, by_who, reason) VALUES (%s,%s,%s,%s,%s)",
            (e.ts, e.scope, e.mode.value, e.by, e.reason),
        )

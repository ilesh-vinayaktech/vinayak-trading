# ruff: noqa: E501
"""Read-only numbers for the two dashboards: one person's own view, and the operations view for staff.
Counts only; nothing here returns a secret, and the person view never looks at anyone else's rows."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg

from algo.portal import audit, kite_vault

OPEN_TICKET = "status IN ('OPEN', 'PENDING')"


def _counts(conn: psycopg.Connection, column: str) -> dict[str, int]:
    rows = conn.execute(f"SELECT {column}, count(*) FROM portal_user GROUP BY 1").fetchall()  # noqa: S608 (fixed column names)
    return {k: int(n) for k, n in rows}


def _tasks(conn: psycopg.Connection, now: datetime, owner: UUID | None) -> dict[str, int]:
    row = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE due_date < %s) FROM portal_task WHERE status='OPEN' AND (%s::uuid IS NULL OR owner_id=%s)",
        (now.date(), owner, owner),
    ).fetchone()
    assert row is not None
    return {"open": int(row[0]), "overdue": int(row[1])}


def mine(
    conn: psycopg.Connection, *, user_id: UUID, now: datetime, public_url: str
) -> dict[str, Any]:
    tickets = conn.execute(
        f"SELECT ticket_id, number, subject, status, updated_at FROM portal_ticket WHERE user_id=%s AND {OPEN_TICKET} ORDER BY updated_at DESC",  # noqa: S608
        (user_id,),
    ).fetchall()
    who = conn.execute(
        "SELECT totp_enabled, last_login_at FROM portal_user WHERE user_id=%s", (user_id,)
    ).fetchone()
    assert who is not None
    sessions = conn.execute(
        "SELECT count(*) FROM portal_session WHERE user_id=%s AND revoked_at IS NULL AND expires_at > %s",
        (user_id, now),
    ).fetchone()
    assert sessions is not None
    return {
        "kite": kite_vault.get_connection(conn, user_id=user_id, now=now, public_url=public_url),
        "tickets": {
            "open": len(tickets),
            "latest": [
                {
                    "ticket_id": str(t[0]),
                    "number": t[1],
                    "subject": t[2],
                    "status": t[3],
                    "updated_at": t[4],
                }
                for t in tickets[:5]
            ],
        },
        "tasks": _tasks(conn, now, user_id),
        "security": {
            "mfa_enabled": who[0],
            "last_login_at": who[1],
            "active_sessions": int(sessions[0]),
        },
    }


def operations(conn: psycopg.Connection, *, now: datetime) -> dict[str, Any]:
    since = now - timedelta(hours=24)
    signins: dict[str, int] = dict(
        conn.execute(
            "SELECT outcome, count(*) FROM portal_login_attempt WHERE at >= %s GROUP BY 1", (since,)
        ).fetchall()
    )
    tickets = conn.execute(
        f"SELECT count(*), count(*) FILTER (WHERE assignee_id IS NULL) FROM portal_ticket WHERE {OPEN_TICKET}"  # noqa: S608
    ).fetchone()
    connected = conn.execute(
        "SELECT count(*) FROM portal_kite_connection WHERE access_token_enc IS NOT NULL AND token_expires_at > %s",
        (now,),
    ).fetchone()
    assert tickets is not None and connected is not None
    return {
        "users": {"by_status": _counts(conn, "status"), "by_role": _counts(conn, "role")},
        "signins": {
            "successes_24h": int(signins.get("SUCCESS", 0)),
            "failures_24h": int(signins.get("FAILURE", 0)),
        },
        "tickets": {"open": int(tickets[0]), "unassigned": int(tickets[1])},
        "tasks": _tasks(conn, now, None),
        "kite": {"connected": int(connected[0]), "feed": kite_vault.system_feed(conn, now=now)},
        "recent": [
            {"id": e["id"], "at": e["at"], "actor": e["actor"], "action": e["action"]}
            for e in audit.recent(conn, limit=8)
        ],
    }

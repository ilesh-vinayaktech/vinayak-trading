# ruff: noqa: E501
"""Server-side sessions. The browser holds an opaque random token in a cookie; the database holds only its SHA-256, so a
database leak does not hand out live sessions. Idle and absolute lifetimes are enforced on every lookup."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import psycopg

IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=12)
TOUCH_EVERY = timedelta(seconds=60)  # last_seen is written at most once a minute per session


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    session_id: UUID
    user_id: UUID
    email: str
    display_name: str
    role: str
    mfa_verified: bool
    totp_enabled: bool
    must_change_password: bool
    csrf_token_hash: str
    expires_at: datetime


def create(
    conn: psycopg.Connection,
    user_id: UUID,
    *,
    now: datetime,
    mfa_verified: bool,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, str]:
    """(session token, csrf token): both are shown to the browser once and never stored in clear."""
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO portal_session (token_hash, user_id, csrf_token_hash, mfa_verified, created_at, last_seen_at, expires_at, ip, user_agent)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            digest(token),
            user_id,
            digest(csrf),
            mfa_verified,
            now,
            now,
            now + ABSOLUTE,
            ip,
            (user_agent or "")[:300] or None,
        ),
    )
    return token, csrf


def lookup(conn: psycopg.Connection, token: str, now: datetime) -> Session | None:
    row = conn.execute(
        "SELECT s.session_id, s.user_id, u.email, u.display_name, u.role, s.mfa_verified, u.totp_enabled,"
        " u.must_change_password, s.csrf_token_hash, s.expires_at, s.last_seen_at"
        " FROM portal_session s JOIN portal_user u USING (user_id)"
        " WHERE s.token_hash=%s AND s.revoked_at IS NULL AND u.status='ACTIVE' AND s.expires_at > %s AND s.last_seen_at > %s",
        (digest(token), now, now - IDLE),
    ).fetchone()
    if row is None:
        return None
    if now - row[10] >= TOUCH_EVERY:
        conn.execute("UPDATE portal_session SET last_seen_at=%s WHERE session_id=%s", (now, row[0]))
    return Session(*row[:10])


def csrf_ok(session: Session, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(digest(provided or ""), session.csrf_token_hash)


def revoke(conn: psycopg.Connection, session_id: UUID, now: datetime) -> None:
    conn.execute(
        "UPDATE portal_session SET revoked_at=%s WHERE session_id=%s AND revoked_at IS NULL",
        (now, session_id),
    )


def revoke_user_sessions(
    conn: psycopg.Connection, user_id: UUID, now: datetime, *, keep: UUID | None = None
) -> int:
    return conn.execute(
        "UPDATE portal_session SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL AND session_id IS DISTINCT FROM %s",
        (now, user_id, keep),
    ).rowcount


def active_for(conn: psycopg.Connection, user_id: UUID, now: datetime) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT session_id, created_at, last_seen_at, expires_at, ip, user_agent FROM portal_session"
        " WHERE user_id=%s AND revoked_at IS NULL AND expires_at > %s AND last_seen_at > %s ORDER BY created_at DESC",
        (user_id, now, now - IDLE),
    ).fetchall()
    keys = ("session_id", "created_at", "last_seen_at", "expires_at", "ip", "user_agent")
    return [dict(zip(keys, r, strict=True)) for r in rows]

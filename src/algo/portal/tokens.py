# ruff: noqa: E501
"""One-time tokens for invitations and password resets. The link carries a random 256-bit value; the database keeps only
its SHA-256, so a database leak does not hand out working links. A token works once and expires; issuing a new one for
the same purpose retires the earlier ones."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import UUID

import psycopg

from algo.portal.sessions import digest

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=2)
TTL = {"INVITE": INVITE_TTL, "RESET": RESET_TTL}


def issue(conn: psycopg.Connection, user_id: UUID, purpose: str, now: datetime) -> str:
    conn.execute(
        "UPDATE portal_token SET used_at=%s WHERE user_id=%s AND purpose=%s AND used_at IS NULL",
        (now, user_id, purpose),
    )
    raw = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO portal_token (token_hash, user_id, purpose, created_at, expires_at) VALUES (%s,%s,%s,%s,%s)",
        (digest(raw), user_id, purpose, now, now + TTL[purpose]),
    )
    return raw


def consume(conn: psycopg.Connection, raw: str, purpose: str, now: datetime) -> UUID | None:
    """The user the token belongs to, and the token is spent; None for an unknown, used, expired or wrong-purpose token."""
    row = conn.execute(
        "UPDATE portal_token SET used_at=%s WHERE token_hash=%s AND purpose=%s AND used_at IS NULL AND expires_at > %s RETURNING user_id",
        (now, digest(raw), purpose, now),
    ).fetchone()
    return UUID(str(row[0])) if row else None


def issued_since(conn: psycopg.Connection, user_id: UUID, purpose: str, since: datetime) -> int:
    row = conn.execute(
        "SELECT count(*) FROM portal_token WHERE user_id=%s AND purpose=%s AND created_at > %s",
        (user_id, purpose, since),
    ).fetchone()
    assert row is not None
    return int(row[0])

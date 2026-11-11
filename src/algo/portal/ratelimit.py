# ruff: noqa: E501
"""Login throttling from the attempt table: no in-process state, so it holds across workers and restarts.

An account is blocked after ACCOUNT_FAILURES failed attempts inside WINDOW since its last success; an address after
IP_FAILURES. Blocked attempts are answered without checking the password, so a blocked attacker learns nothing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import psycopg

WINDOW = timedelta(minutes=15)
ACCOUNT_FAILURES = 5
IP_FAILURES = 30


def email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def record(
    conn: psycopg.Connection, email: str, ip: str | None, *, success: bool, now: datetime
) -> None:
    conn.execute(
        "INSERT INTO portal_login_attempt (email_hash, ip, at, outcome) VALUES (%s,%s,%s,%s)",
        (email_hash(email), ip, now, "SUCCESS" if success else "FAILURE"),
    )


def blocked(conn: psycopg.Connection, email: str, ip: str | None, now: datetime) -> bool:
    since = now - WINDOW
    row = conn.execute(
        "SELECT count(*) FROM portal_login_attempt WHERE email_hash=%s AND outcome='FAILURE' AND at > %s"
        " AND at > COALESCE((SELECT max(at) FROM portal_login_attempt WHERE email_hash=%s AND outcome='SUCCESS'), %s)",
        (email_hash(email), since, email_hash(email), since),
    ).fetchone()
    if row is not None and row[0] >= ACCOUNT_FAILURES:
        return True
    if ip is None:
        return False
    row = conn.execute(
        "SELECT count(*) FROM portal_login_attempt WHERE ip=%s AND outcome='FAILURE' AND at > %s",
        (ip, since),
    ).fetchone()
    return row is not None and row[0] >= IP_FAILURES

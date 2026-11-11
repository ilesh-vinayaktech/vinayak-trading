# ruff: noqa: E501
"""Accounts and authentication: create users, log in (password, then TOTP or a recovery code), change password,
enrol and confirm a second factor. Every outcome is recorded in the audit trail and the login attempt table; errors that
could reveal whether an account exists are identical for an unknown user and a wrong password."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg

from algo.portal import audit, ratelimit, sessions, totp
from algo.portal.crypto import KeyRing, VaultError
from algo.portal.passwords import Hasher, check_policy
from algo.portal.rbac import MFA_REQUIRED, ROLES

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISSUER = "Vinayak Trading"


class AccountError(Exception):
    pass


class DuplicateUser(AccountError):
    pass


class MfaError(AccountError):
    pass


def normalize_email(email: str) -> str:
    e = email.strip().lower()
    if len(e) > 254 or not EMAIL.match(e):
        raise AccountError("enter a valid email address")
    return e


@dataclass(frozen=True)
class LoginResult:
    status: Literal["ok", "mfa_required", "invalid", "mfa_invalid", "blocked"]
    token: str | None = None
    csrf: str | None = None
    user_id: UUID | None = None


def create_user(
    conn: psycopg.Connection,
    hasher: Hasher,
    *,
    email: str,
    display_name: str,
    role: str,
    password: str | None,
    now: datetime,
    created_by: UUID | None = None,
    status: str = "ACTIVE",
    must_change_password: bool = False,
) -> UUID:
    email = normalize_email(email)
    if role not in ROLES:
        raise AccountError(f"unknown role {role!r}")
    if not display_name.strip():
        raise AccountError("a name is required")
    pw_hash = None
    if password is not None:
        check_policy(password, email=email, display_name=display_name)
        pw_hash = hasher.hash(password)
    try:
        row = conn.execute(
            "INSERT INTO portal_user (email, display_name, role, status, password_hash, password_changed_at, must_change_password, created_at, created_by)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING user_id",
            (
                email,
                display_name.strip(),
                role,
                status,
                pw_hash,
                now if pw_hash else None,
                must_change_password,
                now,
                created_by,
            ),
        ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise DuplicateUser("an account with this email already exists") from e
    assert row is not None
    audit.record(
        conn,
        now=now,
        action="user.create",
        actor_user_id=created_by,
        actor_label="admin" if created_by else "system",
        target_type="user",
        target_id=str(row[0]),
        detail={"role": role, "status": status},
    )
    return UUID(str(row[0]))


def _user(conn: psycopg.Connection, email: str) -> Any:
    return conn.execute(
        "SELECT user_id, password_hash, status, totp_enabled, totp_secret_enc, totp_last_step, role FROM portal_user WHERE lower(email)=%s",
        (email,),
    ).fetchone()


def authenticate(
    conn: psycopg.Connection,
    hasher: Hasher,
    ring: KeyRing,
    *,
    email: str,
    password: str,
    totp_code: str | None,
    ip: str | None,
    user_agent: str | None,
    now: datetime,
) -> LoginResult:
    try:
        email = normalize_email(email)
    except AccountError:
        hasher.burn(password)
        return LoginResult("invalid")
    if ratelimit.blocked(conn, email, ip, now):
        audit.record(
            conn, now=now, action="auth.blocked", actor_label=email, ip=ip, user_agent=user_agent
        )
        return LoginResult("blocked")

    def fail(
        action: str, user_id: UUID | None, status: Literal["invalid", "mfa_invalid"]
    ) -> LoginResult:
        ratelimit.record(conn, email, ip, success=False, now=now)
        audit.record(
            conn,
            now=now,
            action=action,
            actor_user_id=user_id,
            actor_label=email,
            ip=ip,
            user_agent=user_agent,
        )
        return LoginResult(status)

    row = _user(conn, email)
    if row is None or row[1] is None or row[2] != "ACTIVE":
        hasher.burn(password)  # the same cost as a real check
        return fail("auth.login_failed", None, "invalid")
    user_id, pw_hash, _status, totp_on, secret_enc, last_step, _role = row
    if not hasher.verify(pw_hash, password):
        return fail("auth.login_failed", user_id, "invalid")
    if totp_on:
        if not totp_code:
            return LoginResult("mfa_required")
        if not _second_factor(conn, ring, user_id, secret_enc, last_step, totp_code, now):
            return fail("auth.mfa_failed", user_id, "mfa_invalid")
    if hasher.needs_rehash(pw_hash):
        conn.execute(
            "UPDATE portal_user SET password_hash=%s WHERE user_id=%s",
            (hasher.hash(password), user_id),
        )
    ratelimit.record(conn, email, ip, success=True, now=now)
    conn.execute("UPDATE portal_user SET last_login_at=%s WHERE user_id=%s", (now, user_id))
    token, csrf = sessions.create(
        conn, user_id, now=now, mfa_verified=bool(totp_on), ip=ip, user_agent=user_agent
    )
    audit.record(
        conn,
        now=now,
        action="auth.login",
        actor_user_id=user_id,
        actor_label=email,
        ip=ip,
        user_agent=user_agent,
    )
    return LoginResult("ok", token, csrf, user_id)


def _second_factor(
    conn: psycopg.Connection,
    ring: KeyRing,
    user_id: UUID,
    secret_enc: str,
    last_step: int | None,
    code: str,
    now: datetime,
) -> bool:
    try:
        secret = ring.decrypt(secret_enc, aad=f"user:{user_id}:totp").decode()
    except VaultError:
        return False  # an unreadable seed never lets anyone in
    step = totp.verify(secret, code.strip(), now, last_step=last_step)
    if step is not None:
        conn.execute("UPDATE portal_user SET totp_last_step=%s WHERE user_id=%s", (step, user_id))
        return True
    used = conn.execute(
        "UPDATE portal_recovery_code SET used_at=%s WHERE user_id=%s AND code_hash=%s AND used_at IS NULL",
        (now, user_id, totp.hash_recovery(code)),
    ).rowcount
    if used:
        audit.record(conn, now=now, action="auth.recovery_code_used", actor_user_id=user_id)
    return bool(used)


def needs_enrolment(role: str, totp_enabled: bool) -> bool:
    """Admin and Operator accounts must have a second factor before they can use anything but the enrolment screens."""
    return role in MFA_REQUIRED and not totp_enabled


def change_password(
    conn: psycopg.Connection,
    hasher: Hasher,
    *,
    user_id: UUID,
    current: str,
    new: str,
    now: datetime,
    keep_session: UUID | None,
) -> None:
    row = conn.execute(
        "SELECT password_hash, email, display_name FROM portal_user WHERE user_id=%s", (user_id,)
    ).fetchone()
    if row is None or row[0] is None or not hasher.verify(row[0], current):
        raise AccountError("the current password is not correct")
    if hasher.verify(row[0], new):
        raise AccountError("choose a password you have not used just now")
    check_policy(new, email=row[1], display_name=row[2])
    conn.execute(
        "UPDATE portal_user SET password_hash=%s, password_changed_at=%s, must_change_password=false WHERE user_id=%s",
        (hasher.hash(new), now, user_id),
    )
    ended = sessions.revoke_user_sessions(conn, user_id, now, keep=keep_session)
    audit.record(
        conn,
        now=now,
        action="auth.password_changed",
        actor_user_id=user_id,
        target_type="user",
        target_id=str(user_id),
        detail={"other_sessions_ended": ended},
    )


def begin_mfa_enrolment(
    conn: psycopg.Connection, ring: KeyRing, *, user_id: UUID
) -> tuple[str, str]:
    """A fresh seed, stored encrypted but not yet active: the user proves they can generate codes first."""
    row = conn.execute(
        "SELECT email, totp_enabled FROM portal_user WHERE user_id=%s", (user_id,)
    ).fetchone()
    if row is None:
        raise AccountError("unknown user")
    if row[1]:
        raise MfaError("two-factor authentication is already on")
    secret = totp.new_secret()
    conn.execute(
        "UPDATE portal_user SET totp_secret_enc=%s, totp_last_step=NULL WHERE user_id=%s",
        (ring.encrypt(secret, aad=f"user:{user_id}:totp"), user_id),
    )
    return secret, totp.provisioning_uri(secret, row[0], ISSUER)


def confirm_mfa(
    conn: psycopg.Connection, ring: KeyRing, *, user_id: UUID, code: str, now: datetime
) -> list[str]:
    """Turns the second factor on and returns ten one-time recovery codes (shown once, stored only as hashes)."""
    row = conn.execute(
        "SELECT totp_secret_enc, totp_enabled FROM portal_user WHERE user_id=%s", (user_id,)
    ).fetchone()
    if row is None or row[0] is None or row[1]:
        raise MfaError("start the enrolment first")
    step = totp.verify(
        ring.decrypt(row[0], aad=f"user:{user_id}:totp").decode(), code.strip(), now, last_step=None
    )
    if step is None:
        raise MfaError("that code is not right: check the time on your phone and try the next one")
    codes = totp.new_recovery_codes()
    conn.execute("DELETE FROM portal_recovery_code WHERE user_id=%s", (user_id,))
    for c in codes:
        conn.execute(
            "INSERT INTO portal_recovery_code (user_id, code_hash) VALUES (%s,%s)",
            (user_id, totp.hash_recovery(c)),
        )
    conn.execute(
        "UPDATE portal_user SET totp_enabled=true, totp_last_step=%s WHERE user_id=%s",
        (step, user_id),
    )
    audit.record(
        conn,
        now=now,
        action="auth.mfa_enabled",
        actor_user_id=user_id,
        target_type="user",
        target_id=str(user_id),
    )
    return codes

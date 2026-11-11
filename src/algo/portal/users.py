# ruff: noqa: E501
"""User administration: directory, invitations, role and status changes, password and second-factor resets.

Rules enforced here (not left to the screens): an administrator cannot change their own role or status, the last active
administrator can never be demoted, suspended or disabled, role and status changes end the user's sessions at once, and
every change is recorded in the audit trail with who did it."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg

from algo.portal import accounts, audit, sessions, tokens
from algo.portal.mailer import Mailer
from algo.portal.passwords import Hasher, check_policy
from algo.portal.rbac import ROLES

STATUSES = ("INVITED", "ACTIVE", "SUSPENDED", "DISABLED")
SETTABLE = ("ACTIVE", "SUSPENDED", "DISABLED")
LINK_PATHS = {"INVITE": "/accept-invite", "RESET": "/reset-password"}
RESET_LIMIT, RESET_WINDOW = 3, timedelta(hours=1)  # self-service reset mails per account per hour


class UserError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def link(public_url: str, purpose: str, token: str) -> str:
    return f"{public_url.rstrip('/')}{LINK_PATHS[purpose]}?token={token}"


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_users(
    conn: psycopg.Connection,
    *,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    if role is not None and role not in ROLES:
        raise UserError(f"unknown role {role!r}")
    if status is not None and status not in STATUSES:
        raise UserError(f"unknown status {status!r}")
    where, args = [], []
    if q:
        where.append("(email ILIKE %s OR display_name ILIKE %s)")
        args += [_like(q), _like(q)]
    if role:
        where.append("role = %s")
        args.append(role)
    if status:
        where.append("status = %s")
        args.append(status)
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM portal_user_tag t WHERE t.user_id = portal_user.user_id AND t.tag = %s)"
        )
        args.append(tag.strip().lower())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute("SELECT count(*) FROM portal_user" + clause, args).fetchone()
    assert total is not None
    rows = conn.execute(
        "SELECT user_id, email, display_name, role, status, totp_enabled, last_login_at, created_at,"
        " COALESCE((SELECT array_agg(t.tag ORDER BY t.tag) FROM portal_user_tag t WHERE t.user_id = portal_user.user_id), '{}') FROM portal_user"
        + clause
        + " ORDER BY lower(display_name), email LIMIT %s OFFSET %s",
        (*args, min(max(limit, 1), 100), max(offset, 0)),
    ).fetchall()
    keys = (
        "id",
        "email",
        "name",
        "role",
        "status",
        "mfa_enabled",
        "last_login_at",
        "created_at",
        "tags",
    )
    return {
        "total": int(total[0]),
        "items": [{**dict(zip(keys, r, strict=True)), "id": str(r[0])} for r in rows],
    }


def get_user(conn: psycopg.Connection, user_id: UUID, now: datetime) -> dict[str, Any]:
    row = conn.execute(
        "SELECT u.user_id, u.email, u.display_name, u.role, u.status, u.totp_enabled, u.must_change_password, u.last_login_at,"
        " u.created_at, u.password_changed_at, c.display_name,"
        " (SELECT count(*) FROM portal_recovery_code r WHERE r.user_id=u.user_id AND r.used_at IS NULL)"
        " FROM portal_user u LEFT JOIN portal_user c ON c.user_id=u.created_by WHERE u.user_id=%s",
        (user_id,),
    ).fetchone()
    if row is None:
        raise UserError("no such user", 404)
    keys = (
        "id",
        "email",
        "name",
        "role",
        "status",
        "mfa_enabled",
        "must_change_password",
        "last_login_at",
        "created_at",
        "password_changed_at",
        "created_by",
        "recovery_codes_left",
    )
    out = dict(zip(keys, row, strict=True))
    out["id"] = str(row[0])
    out["tags"] = [
        r[0]
        for r in conn.execute(
            "SELECT tag FROM portal_user_tag WHERE user_id=%s ORDER BY tag", (user_id,)
        ).fetchall()
    ]
    out["active_sessions"] = len(sessions.active_for(conn, user_id, now))
    return out


def _target(conn: psycopg.Connection, user_id: UUID) -> tuple[str, str, str | None]:
    row = conn.execute(
        "SELECT role, status, password_hash FROM portal_user WHERE user_id=%s FOR UPDATE",
        (user_id,),
    ).fetchone()
    if row is None:
        raise UserError("no such user", 404)
    return row[0], row[1], row[2]


def _not_self(actor: UUID, user_id: UUID, what: str) -> None:
    if actor == user_id:
        raise UserError(f"you cannot change your own {what}: ask another administrator", 409)


def _keep_an_admin(conn: psycopg.Connection, role: str, status: str, user_id: UUID) -> None:
    """Called before a change that would take an active administrator out of the active-admin set."""
    if role == "ADMIN" and status == "ACTIVE":
        row = conn.execute(
            "SELECT count(*) FROM portal_user WHERE role='ADMIN' AND status='ACTIVE' AND user_id <> %s",
            (user_id,),
        ).fetchone()
        assert row is not None
        if row[0] == 0:
            raise UserError("this is the last active administrator", 409)


def invite(
    conn: psycopg.Connection,
    hasher: Hasher,
    mailer: Mailer,
    public_url: str,
    *,
    actor: UUID,
    email: str,
    name: str,
    role: str,
    now: datetime,
) -> tuple[UUID, str]:
    try:
        uid = accounts.create_user(
            conn,
            hasher,
            email=email,
            display_name=name,
            role=role,
            password=None,
            now=now,
            created_by=actor,
            status="INVITED",
        )
    except accounts.DuplicateUser as e:
        raise UserError(str(e), 409) from e
    except accounts.AccountError as e:
        raise UserError(str(e)) from e
    url = link(public_url, "INVITE", tokens.issue(conn, uid, "INVITE", now))
    mailer.send(
        accounts.normalize_email(email),
        "You are invited to the Vinayak trading console",
        f"Open this link within 7 days to choose your password:\n{url}",
    )
    audit.record(
        conn,
        now=now,
        action="user.invited",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(uid),
        detail={"role": role},
    )
    return uid, url


def reissue_invite(
    conn: psycopg.Connection,
    mailer: Mailer,
    public_url: str,
    *,
    actor: UUID,
    user_id: UUID,
    now: datetime,
) -> str:
    _, status, _ = _target(conn, user_id)
    if status != "INVITED":
        raise UserError("only a pending invitation can be sent again", 409)
    email = conn.execute("SELECT email FROM portal_user WHERE user_id=%s", (user_id,)).fetchone()
    assert email is not None
    url = link(public_url, "INVITE", tokens.issue(conn, user_id, "INVITE", now))
    mailer.send(
        email[0],
        "Your invitation to the Vinayak trading console",
        f"Open this link within 7 days to choose your password:\n{url}",
    )
    audit.record(
        conn,
        now=now,
        action="user.invite_resent",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
    )
    return url


def accept_invite(
    conn: psycopg.Connection, hasher: Hasher, *, token: str, password: str, now: datetime
) -> UUID:
    uid = tokens.consume(conn, token, "INVITE", now)
    if uid is None:
        raise UserError("this invitation link is not valid any more")
    row = conn.execute(
        "SELECT email, display_name, status FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone()
    if row is None or row[2] != "INVITED":
        raise UserError("this invitation link is not valid any more")
    check_policy(password, email=row[0], display_name=row[1])
    conn.execute(
        "UPDATE portal_user SET password_hash=%s, password_changed_at=%s, status='ACTIVE' WHERE user_id=%s",
        (hasher.hash(password), now, uid),
    )
    audit.record(
        conn,
        now=now,
        action="user.invite_accepted",
        actor_user_id=uid,
        actor_label=row[0],
        target_type="user",
        target_id=str(uid),
    )
    return uid


def request_reset(
    conn: psycopg.Connection, mailer: Mailer, public_url: str, *, email: str, now: datetime
) -> None:
    """Self-service 'forgot password'. Always looks the same to the caller: an unknown, inactive or over-limit account sends nothing."""
    try:
        e = accounts.normalize_email(email)
    except accounts.AccountError:
        return
    row = conn.execute(
        "SELECT user_id FROM portal_user WHERE lower(email)=%s AND status='ACTIVE'", (e,)
    ).fetchone()
    if row is None or tokens.issued_since(conn, row[0], "RESET", now - RESET_WINDOW) >= RESET_LIMIT:
        return
    url = link(public_url, "RESET", tokens.issue(conn, row[0], "RESET", now))
    mailer.send(
        e,
        "Reset your Vinayak console password",
        f"Open this link within 2 hours to choose a new password. If you did not ask for this, ignore this message.\n{url}",
    )
    audit.record(
        conn,
        now=now,
        action="auth.reset_requested",
        actor_label=e,
        target_type="user",
        target_id=str(row[0]),
    )


def admin_reset_password(
    conn: psycopg.Connection,
    mailer: Mailer,
    public_url: str,
    *,
    actor: UUID,
    user_id: UUID,
    now: datetime,
) -> str:
    _, status, _ = _target(conn, user_id)
    if status != "ACTIVE":
        raise UserError("only an active account can be sent a reset link", 409)
    email = conn.execute("SELECT email FROM portal_user WHERE user_id=%s", (user_id,)).fetchone()
    assert email is not None
    url = link(public_url, "RESET", tokens.issue(conn, user_id, "RESET", now))
    mailer.send(
        email[0],
        "Reset your Vinayak console password",
        f"An administrator started a password reset for you. Open this link within 2 hours:\n{url}",
    )
    audit.record(
        conn,
        now=now,
        action="user.reset_sent",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
    )
    return url


def complete_reset(
    conn: psycopg.Connection, hasher: Hasher, *, token: str, password: str, now: datetime
) -> UUID:
    uid = tokens.consume(conn, token, "RESET", now)
    if uid is None:
        raise UserError("this reset link is not valid any more")
    row = conn.execute(
        "SELECT email, display_name, status FROM portal_user WHERE user_id=%s", (uid,)
    ).fetchone()
    if row is None or row[2] != "ACTIVE":
        raise UserError("this reset link is not valid any more")
    check_policy(password, email=row[0], display_name=row[1])
    conn.execute(
        "UPDATE portal_user SET password_hash=%s, password_changed_at=%s, must_change_password=false WHERE user_id=%s",
        (hasher.hash(password), now, uid),
    )
    ended = sessions.revoke_user_sessions(
        conn, uid, now
    )  # whoever had the old password is signed out
    audit.record(
        conn,
        now=now,
        action="auth.password_reset",
        actor_user_id=uid,
        actor_label=row[0],
        target_type="user",
        target_id=str(uid),
        detail={"sessions_ended": ended},
    )
    return uid


def set_role(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, role: str, now: datetime
) -> None:
    if role not in ROLES:
        raise UserError(f"unknown role {role!r}")
    _not_self(actor, user_id, "role")
    old, status, _ = _target(conn, user_id)
    if old == role:
        return
    if role != "ADMIN":
        _keep_an_admin(conn, old, status, user_id)
    conn.execute("UPDATE portal_user SET role=%s WHERE user_id=%s", (role, user_id))
    ended = sessions.revoke_user_sessions(conn, user_id, now)
    audit.record(
        conn,
        now=now,
        action="user.role_changed",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
        detail={"from": old, "to": role, "sessions_ended": ended},
    )


def set_status(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, status: str, now: datetime
) -> None:
    if status not in SETTABLE:
        raise UserError(f"status must be one of {', '.join(SETTABLE)}")
    _not_self(actor, user_id, "status")
    role, old, pw = _target(conn, user_id)
    if old == status:
        return
    if status == "ACTIVE" and pw is None:
        raise UserError("this person has not accepted their invitation yet", 409)
    if status != "ACTIVE":
        _keep_an_admin(conn, role, old, user_id)
    conn.execute("UPDATE portal_user SET status=%s WHERE user_id=%s", (status, user_id))
    ended = sessions.revoke_user_sessions(conn, user_id, now)
    audit.record(
        conn,
        now=now,
        action="user.status_changed",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
        detail={"from": old, "to": status, "sessions_ended": ended},
    )


def rename(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, name: str, now: datetime
) -> None:
    name = name.strip()
    if not name or len(name) > 120:
        raise UserError("a name of 1 to 120 characters is required")
    _target(conn, user_id)
    conn.execute("UPDATE portal_user SET display_name=%s WHERE user_id=%s", (name, user_id))
    audit.record(
        conn,
        now=now,
        action="user.renamed",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
    )


def reset_mfa(conn: psycopg.Connection, *, actor: UUID, user_id: UUID, now: datetime) -> None:
    """For a lost authenticator: removes the second factor and its recovery codes and signs the user out. An administrator or
    operator is asked to enrol again at their next sign-in."""
    _not_self(actor, user_id, "two-factor setup")
    _target(conn, user_id)
    conn.execute(
        "UPDATE portal_user SET totp_enabled=false, totp_secret_enc=NULL, totp_last_step=NULL WHERE user_id=%s",
        (user_id,),
    )
    conn.execute("DELETE FROM portal_recovery_code WHERE user_id=%s", (user_id,))
    ended = sessions.revoke_user_sessions(conn, user_id, now)
    audit.record(
        conn,
        now=now,
        action="user.mfa_reset",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
        detail={"sessions_ended": ended},
    )


def end_sessions(conn: psycopg.Connection, *, actor: UUID, user_id: UUID, now: datetime) -> int:
    _target(conn, user_id)
    ended = sessions.revoke_user_sessions(conn, user_id, now)
    audit.record(
        conn,
        now=now,
        action="user.sessions_ended",
        actor_user_id=actor,
        actor_label="admin",
        target_type="user",
        target_id=str(user_id),
        detail={"sessions_ended": ended},
    )
    return ended

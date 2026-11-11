# ruff: noqa: E501
"""Staff-only CRM on users: notes, tags and follow-up tasks. None of it is ever returned to the person it is about
(the routes require crm:read / crm:write, which only Admin and Operator hold). Every change is audited."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg

from algo.portal import audit
from algo.portal.rbac import can

TAG = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,29}$")


class CrmError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _user_exists(conn: psycopg.Connection, user_id: UUID) -> None:
    if conn.execute("SELECT 1 FROM portal_user WHERE user_id=%s", (user_id,)).fetchone() is None:
        raise CrmError("no such user", 404)


def add_note(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, body: str, now: datetime
) -> UUID:
    body = body.strip()
    if not 1 <= len(body) <= 4000:
        raise CrmError("a note is 1 to 4000 characters")
    _user_exists(conn, user_id)
    row = conn.execute(
        "INSERT INTO portal_note (user_id, author_id, body, created_at) VALUES (%s,%s,%s,%s) RETURNING note_id",
        (user_id, actor, body, now),
    ).fetchone()
    assert row is not None
    audit.record(
        conn,
        now=now,
        action="crm.note_added",
        actor_user_id=actor,
        actor_label="staff",
        target_type="user",
        target_id=str(user_id),
    )
    return UUID(str(row[0]))


def list_notes(conn: psycopg.Connection, user_id: UUID) -> list[dict[str, Any]]:
    _user_exists(conn, user_id)
    rows = conn.execute(
        "SELECT n.note_id, n.body, n.created_at, a.display_name FROM portal_note n JOIN portal_user a ON a.user_id=n.author_id WHERE n.user_id=%s ORDER BY n.created_at DESC, n.seq DESC",
        (user_id,),
    ).fetchall()
    return [{"id": str(r[0]), "body": r[1], "created_at": r[2], "author": r[3]} for r in rows]


def normalize_tag(tag: str) -> str:
    t = " ".join(tag.strip().lower().split())
    if not TAG.match(t):
        raise CrmError("a tag is 1 to 30 letters, digits, spaces, dashes or underscores")
    return t


def add_tag(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, tag: str, now: datetime
) -> str:
    t = normalize_tag(tag)
    _user_exists(conn, user_id)
    added = conn.execute(
        "INSERT INTO portal_user_tag (user_id, tag, added_by, added_at) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (user_id, t, actor, now),
    ).rowcount
    if added:
        audit.record(
            conn,
            now=now,
            action="crm.tag_added",
            actor_user_id=actor,
            actor_label="staff",
            target_type="user",
            target_id=str(user_id),
            detail={"tag": t},
        )
    return t


def remove_tag(
    conn: psycopg.Connection, *, actor: UUID, user_id: UUID, tag: str, now: datetime
) -> bool:
    t = normalize_tag(tag)
    gone = (
        conn.execute(
            "DELETE FROM portal_user_tag WHERE user_id=%s AND tag=%s", (user_id, t)
        ).rowcount
        > 0
    )
    if gone:
        audit.record(
            conn,
            now=now,
            action="crm.tag_removed",
            actor_user_id=actor,
            actor_label="staff",
            target_type="user",
            target_id=str(user_id),
            detail={"tag": t},
        )
    return gone


def tags_of(conn: psycopg.Connection, user_id: UUID) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT tag FROM portal_user_tag WHERE user_id=%s ORDER BY tag", (user_id,)
        ).fetchall()
    ]


def all_tags(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return [
        {"tag": r[0], "users": r[1]}
        for r in conn.execute(
            "SELECT tag, count(*) FROM portal_user_tag GROUP BY tag ORDER BY tag"
        ).fetchall()
    ]


def create_task(
    conn: psycopg.Connection,
    *,
    actor: UUID,
    title: str,
    detail: str,
    owner_id: UUID,
    user_id: UUID | None,
    due: date | None,
    now: datetime,
) -> UUID:
    title, detail = title.strip(), detail.strip()
    if not 1 <= len(title) <= 200 or len(detail) > 4000:
        raise CrmError("a task needs a title of 1 to 200 characters (detail up to 4000)")
    owner = conn.execute(
        "SELECT role, status FROM portal_user WHERE user_id=%s", (owner_id,)
    ).fetchone()
    if owner is None or owner[1] != "ACTIVE" or not can(owner[0], "crm:write"):
        raise CrmError("a task can only be assigned to an active administrator or operator")
    if user_id is not None:
        _user_exists(conn, user_id)
    row = conn.execute(
        "INSERT INTO portal_task (user_id, owner_id, created_by, title, detail, due_date, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING task_id",
        (user_id, owner_id, actor, title, detail, due, now),
    ).fetchone()
    assert row is not None
    audit.record(
        conn,
        now=now,
        action="crm.task_created",
        actor_user_id=actor,
        actor_label="staff",
        target_type="task",
        target_id=str(row[0]),
        detail={"owner": str(owner_id)},
    )
    return UUID(str(row[0]))


def list_tasks(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    owner_id: UUID | None = None,
    user_id: UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status is not None and status not in ("OPEN", "DONE"):
        raise CrmError("status must be OPEN or DONE")
    where, args = [], []
    for col, val in (("t.status", status), ("t.owner_id", owner_id), ("t.user_id", user_id)):
        if val is not None:
            where.append(f"{col} = %s")
            args.append(val)
    sql = (
        "SELECT t.task_id, t.title, t.detail, t.due_date, t.status, t.created_at, t.completed_at, o.display_name, t.owner_id, s.display_name, t.user_id"
        " FROM portal_task t JOIN portal_user o ON o.user_id=t.owner_id LEFT JOIN portal_user s ON s.user_id=t.user_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY (t.status='DONE'), t.due_date NULLS LAST, t.created_at DESC LIMIT %s"
    )
    rows = conn.execute(sql, (*args, min(max(limit, 1), 200))).fetchall()
    keys = (
        "id",
        "title",
        "detail",
        "due_date",
        "status",
        "created_at",
        "completed_at",
        "owner",
        "owner_id",
        "about",
        "about_id",
    )
    return [
        {
            **dict(zip(keys, r, strict=True)),
            "id": str(r[0]),
            "owner_id": str(r[8]),
            "about_id": str(r[10]) if r[10] else None,
        }
        for r in rows
    ]


def set_task_status(
    conn: psycopg.Connection, *, actor: UUID, task_id: UUID, status: str, now: datetime
) -> None:
    if status not in ("OPEN", "DONE"):
        raise CrmError("status must be OPEN or DONE")
    row = conn.execute(
        "UPDATE portal_task SET status=%s, completed_at=%s WHERE task_id=%s RETURNING task_id",
        (status, now if status == "DONE" else None, task_id),
    ).fetchone()
    if row is None:
        raise CrmError("no such task", 404)
    audit.record(
        conn,
        now=now,
        action="crm.task_done" if status == "DONE" else "crm.task_reopened",
        actor_user_id=actor,
        actor_label="staff",
        target_type="task",
        target_id=str(task_id),
    )

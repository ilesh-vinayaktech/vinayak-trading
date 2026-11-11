# ruff: noqa: E501
"""Support tickets. A person sees only their own tickets and the non-internal messages in them; people who hold
tickets:manage (Admin, Operator) see every ticket, can reply internally, assign and set any status. Object-level access is
enforced here, not by the route alone, so a guessed ticket id of someone else's is indistinguishable from a missing one."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from algo.portal import audit
from algo.portal.rbac import can

STATUSES = ("OPEN", "PENDING", "RESOLVED", "CLOSED")
PRIORITIES = ("LOW", "NORMAL", "HIGH")


class TicketError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _staff(role: str) -> bool:
    return can(role, "tickets:manage")


def _load(conn: psycopg.Connection, ticket_id: UUID, actor: UUID, role: str) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT ticket_id, user_id, status, assignee_id FROM portal_ticket WHERE ticket_id=%s FOR UPDATE",
        (ticket_id,),
    ).fetchone()
    if row is None or (row[1] != actor and not _staff(role)):
        raise TicketError("no such ticket", 404)
    return tuple(row)


def create(
    conn: psycopg.Connection, *, actor: UUID, subject: str, body: str, priority: str, now: datetime
) -> int:
    subject, body = subject.strip(), body.strip()
    if not 1 <= len(subject) <= 200 or not 1 <= len(body) <= 8000:
        raise TicketError(
            "a ticket needs a subject (up to 200 characters) and a message (up to 8000)"
        )
    if priority not in PRIORITIES:
        raise TicketError(f"priority must be one of {', '.join(PRIORITIES)}")
    row = conn.execute(
        "INSERT INTO portal_ticket (user_id, subject, priority, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING ticket_id, number",
        (actor, subject, priority, now, now),
    ).fetchone()
    assert row is not None
    conn.execute(
        "INSERT INTO portal_ticket_message (ticket_id, author_id, body, created_at) VALUES (%s,%s,%s,%s)",
        (row[0], actor, body, now),
    )
    audit.record(
        conn,
        now=now,
        action="ticket.created",
        actor_user_id=actor,
        target_type="ticket",
        target_id=str(row[0]),
        detail={"number": row[1], "priority": priority},
    )
    return int(row[1])


def _summary(r: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "id",
        "number",
        "subject",
        "status",
        "priority",
        "requester",
        "requester_id",
        "assignee",
        "assignee_id",
        "created_at",
        "updated_at",
    )
    d = dict(zip(keys, r, strict=True))
    d["id"], d["requester_id"] = str(r[0]), str(r[6])
    d["assignee_id"] = str(r[8]) if r[8] else None
    return d


_SELECT = (
    "SELECT t.ticket_id, t.number, t.subject, t.status, t.priority, u.display_name, t.user_id, a.display_name, t.assignee_id, t.created_at, t.updated_at"
    " FROM portal_ticket t JOIN portal_user u ON u.user_id=t.user_id LEFT JOIN portal_user a ON a.user_id=t.assignee_id"
)


def list_tickets(
    conn: psycopg.Connection,
    *,
    actor: UUID,
    role: str,
    status: str | None = None,
    mine_only: bool = False,
    assignee_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if status is not None and status not in STATUSES:
        raise TicketError(f"status must be one of {', '.join(STATUSES)}")
    where: list[str] = []
    args: list[Any] = []
    if mine_only or not _staff(role):
        where.append("t.user_id = %s")
        args.append(actor)
    if status:
        where.append("t.status = %s")
        args.append(status)
    if assignee_id is not None and _staff(role):
        where.append("t.assignee_id = %s")
        args.append(assignee_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute("SELECT count(*) FROM portal_ticket t" + clause, args).fetchone()
    assert total is not None
    rows = conn.execute(
        _SELECT + clause + " ORDER BY t.updated_at DESC, t.number DESC LIMIT %s OFFSET %s",
        (*args, min(max(limit, 1), 100), max(offset, 0)),
    ).fetchall()
    return {"total": int(total[0]), "items": [_summary(tuple(r)) for r in rows]}


def get(conn: psycopg.Connection, *, actor: UUID, role: str, ticket_id: UUID) -> dict[str, Any]:
    _load(conn, ticket_id, actor, role)
    head = conn.execute(_SELECT + " WHERE t.ticket_id=%s", (ticket_id,)).fetchone()
    assert head is not None
    staff = _staff(role)
    rows = conn.execute(
        "SELECT m.message_id, m.body, m.internal, m.created_at, a.display_name, m.author_id FROM portal_ticket_message m JOIN portal_user a ON a.user_id=m.author_id"
        " WHERE m.ticket_id=%s"
        + ("" if staff else " AND NOT m.internal")
        + " ORDER BY m.created_at, m.seq",
        (ticket_id,),
    ).fetchall()
    msgs = [
        {
            "id": str(r[0]),
            "body": r[1],
            "internal": r[2],
            "created_at": r[3],
            "author": r[4],
            "mine": r[5] == actor,
        }
        for r in rows
    ]
    return {**_summary(tuple(head)), "messages": msgs}


def reply(
    conn: psycopg.Connection,
    *,
    actor: UUID,
    role: str,
    ticket_id: UUID,
    body: str,
    internal: bool,
    now: datetime,
) -> None:
    body = body.strip()
    if not 1 <= len(body) <= 8000:
        raise TicketError("a message is 1 to 8000 characters")
    _, requester, status, assignee = _load(conn, ticket_id, actor, role)
    staff = _staff(role)
    if internal and not staff:
        raise TicketError("only staff can leave internal notes", 403)
    if status == "CLOSED":
        raise TicketError("this ticket is closed: raise a new one", 409)
    conn.execute(
        "INSERT INTO portal_ticket_message (ticket_id, author_id, body, internal, created_at) VALUES (%s,%s,%s,%s,%s)",
        (ticket_id, actor, body, internal, now),
    )
    new = status
    if not internal:
        if actor == requester and status in ("PENDING", "RESOLVED"):
            new = "OPEN"  # the requester answered or came back: it needs staff again
        elif actor != requester and staff and status == "OPEN":
            new = "PENDING"  # staff answered: now waiting on the requester
    conn.execute(
        "UPDATE portal_ticket SET status=%s, updated_at=%s, assignee_id=COALESCE(assignee_id, %s) WHERE ticket_id=%s",
        (new, now, actor if staff and actor != requester else None, ticket_id),
    )
    audit.record(
        conn,
        now=now,
        action="ticket.reply_internal" if internal else "ticket.reply",
        actor_user_id=actor,
        target_type="ticket",
        target_id=str(ticket_id),
    )


def set_status(
    conn: psycopg.Connection, *, actor: UUID, role: str, ticket_id: UUID, status: str, now: datetime
) -> None:
    if status not in STATUSES:
        raise TicketError(f"status must be one of {', '.join(STATUSES)}")
    _, requester, old, _ = _load(conn, ticket_id, actor, role)
    if not _staff(role) and status != "CLOSED":
        raise TicketError("you can close your own ticket; staff handle the other statuses", 403)
    if old == status:
        return
    conn.execute(
        "UPDATE portal_ticket SET status=%s, updated_at=%s WHERE ticket_id=%s",
        (status, now, ticket_id),
    )
    audit.record(
        conn,
        now=now,
        action="ticket.status_changed",
        actor_user_id=actor,
        target_type="ticket",
        target_id=str(ticket_id),
        detail={"from": old, "to": status},
    )


def assign(
    conn: psycopg.Connection,
    *,
    actor: UUID,
    role: str,
    ticket_id: UUID,
    assignee_id: UUID | None,
    now: datetime,
) -> None:
    if not _staff(role):
        raise TicketError("no such ticket", 404)
    _load(conn, ticket_id, actor, role)
    if assignee_id is not None:
        row = conn.execute(
            "SELECT role, status FROM portal_user WHERE user_id=%s", (assignee_id,)
        ).fetchone()
        if row is None or row[1] != "ACTIVE" or not _staff(row[0]):
            raise TicketError(
                "a ticket can only be assigned to an active administrator or operator"
            )
    conn.execute(
        "UPDATE portal_ticket SET assignee_id=%s, updated_at=%s WHERE ticket_id=%s",
        (assignee_id, now, ticket_id),
    )
    audit.record(
        conn,
        now=now,
        action="ticket.assigned",
        actor_user_id=actor,
        target_type="ticket",
        target_id=str(ticket_id),
        detail={"assignee": str(assignee_id) if assignee_id else None},
    )

# ruff: noqa: E501
"""Append-only audit trail (the database trigger refuses any change or removal). Never put secrets in `detail`."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg


def record(
    conn: psycopg.Connection,
    *,
    now: datetime,
    action: str,
    actor_user_id: Any = None,
    actor_label: str = "system",
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO portal_audit (at, actor_user_id, actor_label, action, target_type, target_id, detail, ip, user_agent, request_id)"
        " VALUES (%s,%s,COALESCE((SELECT email FROM portal_user WHERE user_id=%s), %s),%s,%s,%s,%s,%s,%s,%s) RETURNING audit_id",  # a known actor is named by email, whatever generic label the caller passed
        (
            now,
            actor_user_id,
            actor_user_id,
            actor_label,
            action,
            target_type,
            target_id,
            json.dumps(detail or {}),
            ip,
            (user_agent or "")[:300] or None,
            request_id,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])


def recent(
    conn: psycopg.Connection,
    *,
    limit: int = 50,
    actor_user_id: Any = None,
    target_type: str | None = None,
    target_id: str | None = None,
    action_prefix: str | None = None,
) -> list[dict[str, Any]]:
    where, args = [], []
    if actor_user_id is not None:
        where.append("actor_user_id = %s")
        args.append(actor_user_id)
    if target_type is not None:
        where.append("target_type = %s")
        args.append(target_type)
    if target_id is not None:
        where.append("target_id = %s")
        args.append(target_id)
    if action_prefix is not None:
        where.append("action LIKE %s")
        args.append(
            action_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
    sql = "SELECT audit_id, at, actor_user_id, actor_label, action, target_type, target_id, detail, ip FROM portal_audit"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY audit_id DESC LIMIT %s"
    rows = conn.execute(sql, (*args, min(max(limit, 1), 500))).fetchall()
    keys = (
        "id",
        "at",
        "actor_user_id",
        "actor",
        "action",
        "target_type",
        "target_id",
        "detail",
        "ip",
    )
    return [dict(zip(keys, r, strict=True)) for r in rows]

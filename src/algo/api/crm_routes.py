# ruff: noqa: E501
"""Staff CRM routes: notes, tags and tasks on users, and the list of staff a task or ticket can be assigned to.
All require crm:read / crm:write (Admin and Operator); none of it is visible to the person it is about."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import crm

router = APIRouter(prefix="/api", tags=["crm"])


class NoteBody(BaseModel):
    body: str = Field(max_length=5000)


class TagBody(BaseModel):
    tag: str = Field(max_length=100)


class TaskBody(BaseModel):
    title: str = Field(max_length=300)
    detail: str = Field(default="", max_length=5000)
    owner_id: UUID
    user_id: UUID | None = None
    due_date: date | None = None


class TaskStatusBody(BaseModel):
    status: str = Field(max_length=10)


def _now(request: Request) -> Any:
    st: PortalSettings = request.app.state.portal
    return st.clock.now()


def _fail(e: crm.CrmError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/users/{user_id}/notes")
def notes(user_id: UUID, conn: WConn) -> dict[str, Any]:
    try:
        return {"notes": crm.list_notes(conn, user_id)}
    except crm.CrmError as e:
        raise _fail(e) from e


@router.post("/users/{user_id}/notes")
def add_note(
    user_id: UUID, body: NoteBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    try:
        return {
            "id": str(
                crm.add_note(
                    conn,
                    actor=who.session.user_id,
                    user_id=user_id,
                    body=body.body,
                    now=_now(request),
                )
            )
        }
    except crm.CrmError as e:
        raise _fail(e) from e


@router.post("/users/{user_id}/tags")
def add_tag(
    user_id: UUID, body: TagBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    try:
        return {
            "tag": crm.add_tag(
                conn, actor=who.session.user_id, user_id=user_id, tag=body.tag, now=_now(request)
            )
        }
    except crm.CrmError as e:
        raise _fail(e) from e


@router.post("/users/{user_id}/tags/remove")
def remove_tag(
    user_id: UUID, body: TagBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        return {
            "ok": crm.remove_tag(
                conn, actor=who.session.user_id, user_id=user_id, tag=body.tag, now=_now(request)
            )
        }
    except crm.CrmError as e:
        raise _fail(e) from e


@router.get("/tags")
def tags(conn: WConn) -> dict[str, Any]:
    return {"tags": crm.all_tags(conn)}


@router.get("/staff")
def staff(conn: WConn) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT user_id, display_name, role FROM portal_user WHERE status='ACTIVE' AND role IN ('ADMIN','OPERATOR') ORDER BY lower(display_name)"
    ).fetchall()
    return {"staff": [{"id": str(r[0]), "name": r[1], "role": r[2]} for r in rows]}


@router.get("/tasks")
def tasks(
    who: CurrentUser,
    conn: WConn,
    status: str | None = Query(default=None, max_length=10),
    mine: bool = False,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    try:
        return {
            "tasks": crm.list_tasks(
                conn, status=status, owner_id=who.session.user_id if mine else None, user_id=user_id
            )
        }
    except crm.CrmError as e:
        raise _fail(e) from e


@router.post("/tasks")
def create_task(body: TaskBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    try:
        tid = crm.create_task(
            conn,
            actor=who.session.user_id,
            title=body.title,
            detail=body.detail,
            owner_id=body.owner_id,
            user_id=body.user_id,
            due=body.due_date,
            now=_now(request),
        )
    except crm.CrmError as e:
        raise _fail(e) from e
    return {"id": str(tid)}


@router.post("/tasks/{task_id}/status")
def set_task_status(
    task_id: UUID, body: TaskStatusBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        crm.set_task_status(
            conn, actor=who.session.user_id, task_id=task_id, status=body.status, now=_now(request)
        )
    except crm.CrmError as e:
        raise _fail(e) from e
    return {"ok": True}

# ruff: noqa: E501
"""User directory and administration, and the audit feed. Permissions are declared per route in security.ROUTE_PERMISSIONS."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import audit, users

router = APIRouter(prefix="/api", tags=["users"])


class InviteBody(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(max_length=120)
    role: str = Field(max_length=20)


class NameBody(BaseModel):
    name: str = Field(max_length=500)


class RoleBody(BaseModel):
    role: str = Field(max_length=20)


class StatusBody(BaseModel):
    status: str = Field(max_length=20)


def _settings(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _fail(e: users.UserError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/users")
def list_users(
    conn: WConn,
    q: str | None = Query(default=None, max_length=100),
    role: str | None = Query(default=None, max_length=20),
    status: str | None = Query(default=None, max_length=20),
    tag: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
) -> dict[str, Any]:
    try:
        return users.list_users(
            conn, q=q, role=role, status=status, tag=tag, limit=limit, offset=offset
        )
    except users.UserError as e:
        raise _fail(e) from e


@router.post("/users")
def invite(body: InviteBody, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    st = _settings(request)
    try:
        uid, url = users.invite(
            conn,
            st.hasher,
            st.mailer,
            st.public_url,
            actor=who.session.user_id,
            email=body.email,
            name=body.name,
            role=body.role,
            now=st.clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"id": str(uid), "invite_url": url}


@router.get("/users/{user_id}")
def get_user(user_id: UUID, request: Request, conn: WConn) -> dict[str, Any]:
    try:
        return users.get_user(conn, user_id, _settings(request).clock.now())
    except users.UserError as e:
        raise _fail(e) from e


@router.post("/users/{user_id}/name")
def rename(
    user_id: UUID, body: NameBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        users.rename(
            conn,
            actor=who.session.user_id,
            user_id=user_id,
            name=body.name,
            now=_settings(request).clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/users/{user_id}/role")
def set_role(
    user_id: UUID, body: RoleBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        users.set_role(
            conn,
            actor=who.session.user_id,
            user_id=user_id,
            role=body.role,
            now=_settings(request).clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/users/{user_id}/status")
def set_status(
    user_id: UUID, body: StatusBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        users.set_status(
            conn,
            actor=who.session.user_id,
            user_id=user_id,
            status=body.status,
            now=_settings(request).clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: UUID, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    st = _settings(request)
    try:
        url = users.admin_reset_password(
            conn,
            st.mailer,
            st.public_url,
            actor=who.session.user_id,
            user_id=user_id,
            now=st.clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"reset_url": url}


@router.post("/users/{user_id}/resend-invite")
def resend_invite(user_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    st = _settings(request)
    try:
        url = users.reissue_invite(
            conn,
            st.mailer,
            st.public_url,
            actor=who.session.user_id,
            user_id=user_id,
            now=st.clock.now(),
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"invite_url": url}


@router.post("/users/{user_id}/reset-mfa")
def reset_mfa(user_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    try:
        users.reset_mfa(
            conn, actor=who.session.user_id, user_id=user_id, now=_settings(request).clock.now()
        )
    except users.UserError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/users/{user_id}/end-sessions")
def end_sessions(user_id: UUID, request: Request, who: CurrentUser, conn: WConn) -> dict[str, int]:
    try:
        return {
            "ended": users.end_sessions(
                conn, actor=who.session.user_id, user_id=user_id, now=_settings(request).clock.now()
            )
        }
    except users.UserError as e:
        raise _fail(e) from e


@router.get("/audit")
def audit_feed(
    conn: WConn,
    actor_id: UUID | None = None,
    target_type: str | None = Query(default=None, max_length=40),
    target_id: str | None = Query(default=None, max_length=80),
    action: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {
        "events": audit.recent(
            conn,
            limit=limit,
            actor_user_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            action_prefix=action,
        )
    }

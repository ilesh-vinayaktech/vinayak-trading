# ruff: noqa: E501
"""Support tickets. Everyone signed in (tickets:own) can raise tickets and work their own; staff (tickets:manage, enforced in
algo.portal.tickets per object) see and work all of them."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import tickets

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


class NewTicket(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=10000)
    priority: str = Field(default="NORMAL", max_length=10)


class MessageBody(BaseModel):
    body: str = Field(max_length=10000)
    internal: bool = False


class StatusBody(BaseModel):
    status: str = Field(max_length=10)


class AssignBody(BaseModel):
    assignee_id: UUID | None = None


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _fail(e: tickets.TicketError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("")
def list_tickets(
    request: Request,
    who: CurrentUser,
    conn: WConn,
    status: str | None = Query(default=None, max_length=10),
    mine: bool = False,
    assignee_id: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100000),
) -> dict[str, Any]:
    try:
        return tickets.list_tickets(
            conn,
            actor=who.session.user_id,
            role=who.session.role,
            status=status,
            mine_only=mine,
            assignee_id=assignee_id,
            limit=limit,
            offset=offset,
        )
    except tickets.TicketError as e:
        raise _fail(e) from e


@router.post("")
def create_ticket(
    body: NewTicket, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, int]:
    try:
        return {
            "number": tickets.create(
                conn,
                actor=who.session.user_id,
                subject=body.subject,
                body=body.body,
                priority=body.priority,
                now=_st(request).clock.now(),
            )
        }
    except tickets.TicketError as e:
        raise _fail(e) from e


@router.get("/{ticket_id}")
def get_ticket(ticket_id: UUID, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    try:
        return tickets.get(
            conn, actor=who.session.user_id, role=who.session.role, ticket_id=ticket_id
        )
    except tickets.TicketError as e:
        raise _fail(e) from e


@router.post("/{ticket_id}/messages")
def reply(
    ticket_id: UUID, body: MessageBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        tickets.reply(
            conn,
            actor=who.session.user_id,
            role=who.session.role,
            ticket_id=ticket_id,
            body=body.body,
            internal=body.internal,
            now=_st(request).clock.now(),
        )
    except tickets.TicketError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/{ticket_id}/status")
def set_status(
    ticket_id: UUID, body: StatusBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        tickets.set_status(
            conn,
            actor=who.session.user_id,
            role=who.session.role,
            ticket_id=ticket_id,
            status=body.status,
            now=_st(request).clock.now(),
        )
    except tickets.TicketError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/{ticket_id}/assign")
def assign(
    ticket_id: UUID, body: AssignBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        tickets.assign(
            conn,
            actor=who.session.user_id,
            role=who.session.role,
            ticket_id=ticket_id,
            assignee_id=body.assignee_id,
            now=_st(request).clock.now(),
        )
    except tickets.TicketError as e:
        raise _fail(e) from e
    return {"ok": True}

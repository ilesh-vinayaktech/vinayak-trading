# ruff: noqa: E501
"""The trading calendar: what the live feed will do today, and the exceptions to the regular session (holidays, special
sessions). Staff read it (ops:read) and add or remove special sessions (ops:write); every change is audited."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.live import market_calendar as cal
from algo.portal import audit

router = APIRouter(prefix="/api/market", tags=["market"])
HORIZON = timedelta(days=180)


class SessionBody(BaseModel):
    day: date
    start: time
    end: time
    note: str = Field(default="", max_length=300)


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _hhmm(t: time | None) -> str | None:
    return None if t is None else t.strftime("%H:%M")


@router.get("/calendar")
def calendar(request: Request, conn: WConn) -> dict[str, Any]:
    now = _st(request).clock.now()
    today = now.astimezone(cal.IST).date()
    windows = [
        {"start": _hhmm(s.astimezone(cal.IST).time()), "end": _hhmm(e.astimezone(cal.IST).time())}
        for s, e in cal.windows_for(conn, today)
    ]
    rows = [
        {**r, "day": r["day"].isoformat(), "start": _hhmm(r["start"]), "end": _hhmm(r["end"])}
        for r in cal.list_exceptions(conn, today, today + HORIZON)
    ]
    return {"today": {"day": today.isoformat(), "windows": windows}, "exceptions": rows}


@router.post("/sessions")
def add_session(
    body: SessionBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, int]:
    now = _st(request).clock.now()
    if body.day < now.astimezone(cal.IST).date():
        raise HTTPException(400, "pick today or a later date")
    try:
        sid = cal.add_session(
            conn,
            day=body.day,
            start=body.start,
            end=body.end,
            note=body.note,
            source="manual",
            actor=who.session.user_id,
            now=now,
        )
    except cal.CalendarError as e:
        raise HTTPException(400, str(e)) from e
    audit.record(
        conn, now=now, action="market.session_added", actor_user_id=who.session.user_id, target_type="market_session", target_id=str(sid),
        detail={"day": body.day.isoformat(), "start": _hhmm(body.start), "end": _hhmm(body.end), "note": body.note.strip()},
    )  # fmt: skip
    return {"id": sid}


@router.post("/sessions/{session_id}/remove")
def remove_session(
    session_id: int, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    try:
        cal.remove(conn, session_id)
    except cal.CalendarError as e:
        raise HTTPException(404, str(e)) from e
    audit.record(
        conn,
        now=_st(request).clock.now(),
        action="market.session_removed",
        actor_user_id=who.session.user_id,
        target_type="market_session",
        target_id=str(session_id),
    )
    return {"ok": True}

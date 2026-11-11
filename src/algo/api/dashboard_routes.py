# ruff: noqa: E501
"""Dashboards: `me` is the signed-in person's own summary (nothing about anyone else); `operations` is for staff (ops:read)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import dashboards

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _st(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


@router.get("/me")
def my_dashboard(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    st = _st(request)
    return dashboards.mine(
        conn, user_id=who.session.user_id, now=st.clock.now(), public_url=st.public_url
    )


@router.get("/operations")
def operations_dashboard(request: Request, conn: WConn) -> dict[str, Any]:
    return dashboards.operations(conn, now=_st(request).clock.now())

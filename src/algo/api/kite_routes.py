# ruff: noqa: E501
"""The signed-in user's own Kite connection. Every route acts on the caller's own record: there is no user id in any path, so
no one can reach another person's credentials. Responses never contain the API key, secret or token."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.portal import kite_vault

router = APIRouter(prefix="/api/kite", tags=["kite"])


class CredentialsBody(BaseModel):
    api_key: str = Field(max_length=100)
    api_secret: str = Field(max_length=100)


class CompleteBody(BaseModel):
    request_token: str = Field(max_length=200)
    state: str = Field(max_length=200)


class SystemBody(BaseModel):
    enabled: bool


def _settings(request: Request) -> PortalSettings:
    st: PortalSettings = request.app.state.portal
    return st


def _fail(e: kite_vault.KiteVaultError) -> HTTPException:
    return HTTPException(e.status, str(e))


@router.get("/connection")
def connection(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    st = _settings(request)
    return kite_vault.get_connection(
        conn, user_id=who.session.user_id, now=st.clock.now(), public_url=st.public_url
    )


@router.post("/credentials")
def save_credentials(
    body: CredentialsBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    st = _settings(request)
    try:
        kite_vault.save_credentials(
            conn,
            st.ring,
            user_id=who.session.user_id,
            api_key=body.api_key,
            api_secret=body.api_secret,
            now=st.clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e
    return {"ok": True}


@router.post("/credentials/remove")
def remove_credentials(request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    return {
        "ok": kite_vault.remove_credentials(
            conn, user_id=who.session.user_id, now=_settings(request).clock.now()
        )
    }


@router.post("/connect/start")
def connect_start(request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    st = _settings(request)
    try:
        return {
            "login_url": kite_vault.begin_connect(
                conn, st.ring, user_id=who.session.user_id, now=st.clock.now()
            )
        }
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e


@router.post("/connect/complete")
def connect_complete(
    body: CompleteBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, str]:
    st = _settings(request)
    try:
        kite_user = kite_vault.complete_connect(
            conn,
            st.ring,
            st.kite_http,
            user_id=who.session.user_id,
            request_token=body.request_token,
            state=body.state,
            now=st.clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        conn.commit()  # a refused attempt keeps its state spent (and its audit entry)
        raise _fail(e) from e
    return {"kite_user": kite_user}


@router.post("/disconnect")
def disconnect(request: Request, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    kite_vault.disconnect(conn, user_id=who.session.user_id, now=_settings(request).clock.now())
    return {"ok": True}


@router.get("/system")
def system_feed(request: Request, conn: WConn) -> dict[str, Any]:
    return {"feed": kite_vault.system_feed(conn, now=_settings(request).clock.now())}


@router.post("/system")
def set_system_feed(
    body: SystemBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    """The administrator's own connection becomes (or stops being) the data feed the loaders use."""
    try:
        kite_vault.set_system_feed(
            conn,
            actor=who.session.user_id,
            user_id=who.session.user_id,
            enabled=body.enabled,
            now=_settings(request).clock.now(),
        )
    except kite_vault.KiteVaultError as e:
        raise _fail(e) from e
    return {"ok": True}

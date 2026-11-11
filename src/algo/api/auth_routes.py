# ruff: noqa: E501
"""Sign-in, sign-out and the signed-in user's own security settings."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from algo.api.security import CSRF_COOKIE, CurrentUser, PortalSettings, Principal, WConn, client_ip
from algo.portal import accounts, audit, sessions
from algo.portal.passwords import PasswordPolicyError
from algo.portal.rbac import permissions_of

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(
        max_length=256
    )  # bounded so a huge value cannot be used to burn hashing time
    totp_code: str | None = Field(default=None, max_length=32)


class PasswordBody(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class CodeBody(BaseModel):
    code: str = Field(max_length=32)


def user_payload(p: Principal) -> dict[str, Any]:
    s = p.session
    return {
        "id": str(s.user_id),
        "email": s.email,
        "name": s.display_name,
        "role": s.role,
        "permissions": sorted(p.permissions),
        "mfa_enabled": s.totp_enabled,
        "enrolment_required": p.enrolment_required,
        "must_change_password": s.must_change_password,
    }


def _set_cookies(response: Response, settings: PortalSettings, token: str, csrf: str) -> None:
    life = int(sessions.ABSOLUTE.total_seconds())
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=life,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    # readable by the page's script so it can echo the value in a header; useless to another site
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=life,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, conn: WConn) -> dict[str, Any]:
    st: PortalSettings = request.app.state.portal
    now = st.clock.now()
    r = accounts.authenticate(
        conn,
        st.hasher,
        st.ring,
        email=body.email,
        password=body.password,
        totp_code=body.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        now=now,
    )
    conn.commit()  # keep the attempt record and audit entry even when the answer below is an error
    if r.status == "blocked":
        raise HTTPException(
            429, "Too many attempts. Try again in a few minutes.", headers={"Retry-After": "900"}
        )
    if r.status == "mfa_required":
        return {"mfa_required": True}
    if r.status == "mfa_invalid":
        raise HTTPException(401, "That code is not valid.")
    if r.status != "ok" or r.token is None or r.csrf is None:
        raise HTTPException(401, "Invalid email or password.")
    _set_cookies(response, st, r.token, r.csrf)
    s = sessions.lookup(conn, r.token, now)
    assert s is not None
    return {
        "user": user_payload(
            Principal(s, permissions_of(s.role), accounts.needs_enrolment(s.role, s.totp_enabled))
        )
    }


@router.post("/logout")
def logout(request: Request, response: Response, who: CurrentUser, conn: WConn) -> dict[str, bool]:
    st: PortalSettings = request.app.state.portal
    sessions.revoke(conn, who.session.session_id, st.clock.now())
    audit.record(
        conn,
        now=st.clock.now(),
        action="auth.logout",
        actor_user_id=who.session.user_id,
        actor_label=who.session.email,
        ip=client_ip(request),
    )
    response.delete_cookie(st.cookie_name, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(who: CurrentUser) -> dict[str, Any]:
    return {"user": user_payload(who)}


@router.post("/password")
def change_password(
    body: PasswordBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    st: PortalSettings = request.app.state.portal
    try:
        accounts.change_password(
            conn,
            st.hasher,
            user_id=who.session.user_id,
            current=body.current,
            new=body.new,
            now=st.clock.now(),
            keep_session=who.session.session_id,
        )
    except (accounts.AccountError, PasswordPolicyError) as e:
        raise HTTPException(422, str(e)) from e
    return {"ok": True}


@router.post("/mfa/enrol")
def mfa_enrol(request: Request, who: CurrentUser, conn: WConn) -> dict[str, str]:
    st: PortalSettings = request.app.state.portal
    try:
        secret, uri = accounts.begin_mfa_enrolment(conn, st.ring, user_id=who.session.user_id)
    except accounts.AccountError as e:
        raise HTTPException(409, str(e)) from e
    return {"secret": secret, "uri": uri}


@router.post("/mfa/confirm")
def mfa_confirm(
    body: CodeBody, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, list[str]]:
    st: PortalSettings = request.app.state.portal
    try:
        codes = accounts.confirm_mfa(
            conn, st.ring, user_id=who.session.user_id, code=body.code, now=st.clock.now()
        )
    except accounts.AccountError as e:
        raise HTTPException(422, str(e)) from e
    return {"recovery_codes": codes}


@router.get("/sessions")
def list_sessions(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    st: PortalSettings = request.app.state.portal
    rows = sessions.active_for(conn, who.session.user_id, st.clock.now())
    return {
        "sessions": [
            {
                **{k: (str(v) if k == "session_id" else v) for k, v in r.items()},
                "current": r["session_id"] == who.session.session_id,
            }
            for r in rows
        ]
    }


@router.delete("/sessions/{session_id}")
def end_session(
    session_id: UUID, request: Request, who: CurrentUser, conn: WConn
) -> dict[str, bool]:
    st: PortalSettings = request.app.state.portal
    owned = conn.execute(
        "SELECT 1 FROM portal_session WHERE session_id=%s AND user_id=%s",
        (session_id, who.session.user_id),
    ).fetchone()
    if owned is None:
        raise HTTPException(
            404, "No such session"
        )  # also what another user's session id looks like
    sessions.revoke(conn, session_id, st.clock.now())
    audit.record(
        conn,
        now=st.clock.now(),
        action="auth.session_revoked",
        actor_user_id=who.session.user_id,
        target_type="session",
        target_id=str(session_id),
    )
    return {"ok": True}

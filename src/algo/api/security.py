# ruff: noqa: E501
"""Authentication and authorisation for every /api route: deny by default.

A request is allowed only if it is one of the PUBLIC routes, or it carries a live session cookie and the user's role holds
the route's permission. Unsafe methods (POST, PUT, PATCH, DELETE) also need the CSRF header matching the session and an
Origin that is one of ours. Accounts that must enrol a second factor or change a temporary password can reach only the
screens that do that. The guard runs as an app-wide dependency, so a new route is protected without anyone remembering to."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, Request

from algo.core.clock import Clock
from algo.portal import accounts, sessions
from algo.portal.crypto import KeyRing
from algo.portal.passwords import Hasher
from algo.portal.rbac import can, permissions_of

WRITE_OPTIONS = "-c statement_timeout=15000 -c idle_in_transaction_session_timeout=30000"
SESSION_COOKIE, SESSION_COOKIE_SECURE = (
    "session",
    "__Host-session",
)  # the __Host- prefix needs Secure (HTTPS)
CSRF_COOKIE, CSRF_HEADER = "csrf", "x-csrf-token"
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SELF = "self"  # any signed-in user
DEFAULT_PERMISSION = "research:read"
PUBLIC = frozenset({("GET", "/api/health"), ("POST", "/api/auth/login")})
ROUTE_PERMISSIONS = {
    ("GET", "/api/auth/me"): SELF,
    ("POST", "/api/auth/logout"): SELF,
    ("POST", "/api/auth/password"): SELF,
    ("POST", "/api/auth/mfa/enrol"): SELF,
    ("POST", "/api/auth/mfa/confirm"): SELF,
    ("GET", "/api/auth/sessions"): SELF,
    ("DELETE", "/api/auth/sessions/{session_id}"): SELF,
    ("GET", "/api/system/activity"): "ops:read",
    ("GET", "/api/reviews"): "ops:read",
    ("GET", "/api/reviews/{item_id}/history"): "ops:read",
    ("POST", "/api/reviews/{item_id}/decisions"): "ops:write",
}
# the only routes an account can use while it still has to enrol a second factor or replace a temporary password
RESTRICTED_OK = frozenset(
    {
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/password"),
        ("POST", "/api/auth/mfa/enrol"),
        ("POST", "/api/auth/mfa/confirm"),
    }
)


@dataclass(frozen=True)
class PortalSettings:
    hasher: Hasher
    ring: KeyRing
    clock: Clock
    origins: tuple[str, ...]
    cookie_secure: bool = True
    trust_proxy: bool = (
        False  # True only behind a proxy that appends the real client address to X-Forwarded-For
    )

    @property
    def cookie_name(self) -> str:
        return SESSION_COOKIE_SECURE if self.cookie_secure else SESSION_COOKIE


@dataclass(frozen=True)
class Principal:
    session: sessions.Session
    permissions: frozenset[str]
    enrolment_required: bool

    @property
    def restricted(self) -> bool:
        return self.enrolment_required or self.session.must_change_password


def get_write_conn(request: Request) -> Iterator[psycopg.Connection]:
    """The portal's writable session (accounts, sessions, audit). Research queries keep their read-only sessions."""
    with psycopg.connect(request.app.state.dsn, options=WRITE_OPTIONS, connect_timeout=5) as c:
        yield c


WConn = Annotated[psycopg.Connection, Depends(get_write_conn)]


def client_ip(request: Request) -> str | None:
    settings: PortalSettings = request.app.state.portal
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else None


def guard(request: Request) -> None:
    route = request.scope.get("route")
    key = (request.method, getattr(route, "path", request.url.path))
    if key in PUBLIC:
        return
    settings: PortalSettings = request.app.state.portal
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(401, "Not signed in")
    with psycopg.connect(request.app.state.dsn, options=WRITE_OPTIONS, connect_timeout=5) as conn:
        session = sessions.lookup(conn, token, settings.clock.now())
    if session is None:
        raise HTTPException(401, "Not signed in")
    principal = Principal(
        session,
        permissions_of(session.role),
        accounts.needs_enrolment(session.role, session.totp_enabled),
    )
    if principal.restricted and key not in RESTRICTED_OK:
        raise HTTPException(
            403,
            "enrolment_required" if principal.enrolment_required else "password_change_required",
        )
    needed = ROUTE_PERMISSIONS.get(key, DEFAULT_PERMISSION)
    if needed != SELF and not can(session.role, needed):
        raise HTTPException(403, "Not permitted")
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.origins:
            raise HTTPException(403, "Origin not allowed")
        if not sessions.csrf_ok(session, request.headers.get(CSRF_HEADER)):
            raise HTTPException(403, "CSRF check failed")
    request.state.principal = principal


def current_principal(request: Request) -> Principal:
    """The signed-in user for a route (the guard has already run and rejected everyone else)."""
    principal: Principal = request.state.principal
    return principal


CurrentUser = Annotated[Principal, Depends(current_principal)]

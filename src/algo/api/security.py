# ruff: noqa: E501
"""Authentication and authorisation for every /api route: deny by default.

A request is allowed only if it is one of the PUBLIC routes, or it carries a live session cookie and the user's role holds
the route's permission. Unsafe methods (POST, PUT, PATCH, DELETE) also need the CSRF header matching the session and an
Origin that is one of ours. Accounts that must enrol a second factor or change a temporary password can reach only the
screens that do that. The guard runs as an app-wide dependency, so a new route is protected without anyone remembering to."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated

import psycopg
from fastapi import Depends, HTTPException, Request

from algo.core.clock import Clock
from algo.data.providers.kite_session import urllib_http
from algo.portal import accounts, sessions
from algo.portal.crypto import KeyRing
from algo.portal.mailer import ConsoleMailer, Mailer
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
PUBLIC = frozenset(
    {
        ("GET", "/api/health"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/forgot"),
        ("POST", "/api/auth/accept-invite"),
        ("POST", "/api/auth/reset-password"),
    }
)
ROUTE_PERMISSIONS = {
    ("GET", "/api/auth/me"): SELF,
    ("POST", "/api/auth/logout"): SELF,
    ("POST", "/api/auth/password"): SELF,
    ("POST", "/api/auth/mfa/enrol"): SELF,
    ("POST", "/api/auth/mfa/confirm"): SELF,
    ("GET", "/api/auth/sessions"): SELF,
    ("GET", "/api/dashboard/me"): SELF,
    ("GET", "/api/market/calendar"): "ops:read",
    ("POST", "/api/screener/run"): "research:read",
    (
        "POST",
        "/api/market/watchlist",
    ): "research:read",  # a personal list: anyone who can read research may keep one
    ("DELETE", "/api/market/watchlist/{instrument_id}"): "research:read",
    ("GET", "/api/costs/schedules"): "research:read",
    ("GET", "/api/costs/preview"): "research:read",
    ("POST", "/api/costs/providers"): "system:settings",
    ("POST", "/api/costs/schedules/{schedule_id}/{version}/verify"): "system:settings",
    ("POST", "/api/costs/schedules/{schedule_id}/{version}/backfill"): "system:settings",
    ("POST", "/api/costs/schedules/{schedule_id}/{version}/new-version"): "system:settings",
    ("POST", "/api/costs/schedules/{schedule_id}/{version}/remove"): "system:settings",
    ("GET", "/api/holdout"): "holdout:read",
    ("GET", "/api/pipeline"): "research:read",
    ("GET", "/api/pipeline/unrun"): "research:read",
    ("POST", "/api/holdout/cutoffs/{cutoff_id}/freeze"): "holdout:read",
    ("POST", "/api/holdout/submit"): "holdout:read",
    ("GET", "/api/paper/account"): "strategy:own",
    ("POST", "/api/paper/account"): "strategy:own",
    ("POST", "/api/paper/account/settings"): "strategy:own",
    (
        "GET",
        "/api/paper/definitions",
    ): "holdout:read",  # shows candidate-level holdout state: owner only (policy v3 section 5)
    (
        "POST",
        "/api/paper/definitions/{experiment_id}/start",
    ): "holdout:read",  # its refusals would reveal the verdict
    (
        "GET",
        "/api/risk",
    ): "research:read",  # anyone may look; changing needs strategy:own (own strategy) or ops:write (everyone)
    ("PUT", "/api/risk/limits"): "strategy:own",
    ("POST", "/api/risk/switch"): "strategy:own",
    ("POST", "/api/risk/switch/global"): "ops:write",
    ("POST", "/api/regulatory"): "ops:write",
    ("POST", "/api/regulatory/{topic}/verify"): "ops:write",
    ("GET", "/api/paper/summary"): "strategy:own",
    ("GET", "/api/paper/orders"): "strategy:own",
    ("POST", "/api/paper/orders/{order_id}/approve"): "strategy:own",
    ("POST", "/api/paper/orders/{order_id}/reject"): "strategy:own",
    ("GET", "/api/paper/runs"): "strategy:own",
    ("GET", "/api/strategies"): "strategy:own",
    ("POST", "/api/studies"): "strategy:own",
    ("POST", "/api/families"): "strategy:own",
    ("POST", "/api/studies/{experiment_id}/runs"): "strategy:own",
    ("POST", "/api/studies/{experiment_id}/verdicts"): "strategy:own",
    ("POST", "/api/studies/{experiment_id}/holdout"): "strategy:own",
    ("POST", "/api/studies/runs/{run_id}/cancel"): "strategy:own",
    ("POST", "/api/strategies/definitions/{strategy_id}/{version}/study"): "strategy:own",
    ("GET", "/api/strategies/definitions/{strategy_id}/{version}/signals"): "strategy:own",
    ("POST", "/api/strategies"): "strategy:own",
    ("GET", "/api/strategies/{config_id}/stage"): "strategy:own",
    ("POST", "/api/strategies/{config_id}/stage"): "strategy:own",
    ("GET", "/api/strategies/{config_id}/signals"): "strategy:own",
    ("POST", "/api/strategies/{config_id}"): "strategy:own",
    ("POST", "/api/strategies/{config_id}/use"): "strategy:own",
    ("POST", "/api/strategies/{config_id}/delete"): "strategy:own",
    ("POST", "/api/market/sessions"): "ops:write",
    ("POST", "/api/market/sessions/{session_id}/remove"): "ops:write",
    ("GET", "/api/dashboard/operations"): "ops:read",
    ("DELETE", "/api/auth/sessions/{session_id}"): SELF,
    ("GET", "/api/users/{user_id}/notes"): "crm:read",
    ("POST", "/api/users/{user_id}/notes"): "crm:write",
    ("POST", "/api/users/{user_id}/tags"): "crm:write",
    ("POST", "/api/users/{user_id}/tags/remove"): "crm:write",
    ("GET", "/api/tags"): "crm:read",
    ("GET", "/api/staff"): "crm:read",
    ("GET", "/api/tasks"): "crm:read",
    ("POST", "/api/tasks"): "crm:write",
    ("POST", "/api/tasks/{task_id}/status"): "crm:write",
    ("GET", "/api/tickets"): "tickets:own",
    ("POST", "/api/tickets"): "tickets:own",
    ("GET", "/api/tickets/{ticket_id}"): "tickets:own",
    ("POST", "/api/tickets/{ticket_id}/messages"): "tickets:own",
    (
        "POST",
        "/api/tickets/{ticket_id}/status",
    ): "tickets:own",  # object-level: own ticket, or tickets:manage
    ("POST", "/api/tickets/{ticket_id}/assign"): "tickets:manage",
    ("GET", "/api/kite/connection"): "kite:own",
    ("GET", "/api/kite/account"): "kite:own",
    ("POST", "/api/kite/credentials"): "kite:own",
    ("POST", "/api/kite/credentials/remove"): "kite:own",
    ("POST", "/api/kite/connect/start"): "kite:own",
    ("POST", "/api/kite/connect/complete"): "kite:own",
    ("POST", "/api/kite/disconnect"): "kite:own",
    ("GET", "/api/kite/system"): "system:settings",
    ("POST", "/api/kite/system"): "system:settings",
    ("GET", "/api/users"): "users:read",
    ("GET", "/api/users/{user_id}"): "users:read",
    (
        "POST",
        "/api/users",
    ): "users:write",  # the route also requires roles:write: choosing a role is a role decision
    ("POST", "/api/users/{user_id}/name"): "users:write",
    ("POST", "/api/users/{user_id}/role"): "roles:write",
    ("POST", "/api/users/{user_id}/status"): "users:write",
    ("POST", "/api/users/{user_id}/reset-password"): "users:write",
    ("POST", "/api/users/{user_id}/resend-invite"): "users:write",
    ("POST", "/api/users/{user_id}/reset-mfa"): "users:write",
    ("POST", "/api/users/{user_id}/end-sessions"): "users:write",
    ("GET", "/api/audit"): "audit:read",
    ("GET", "/api/system/activity"): "ops:read",
    ("GET", "/api/corporate-actions/review"): "ops:read",
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
    mailer: Mailer = field(default_factory=ConsoleMailer)
    public_url: str = "http://localhost:3000"  # what links in invitation and reset mails point to
    kite_http: Callable[..., tuple[int, bytes]] = (
        urllib_http  # the transport to Kite (replaced in tests)
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

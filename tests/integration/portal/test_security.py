from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from algo.api import security
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.portal import accounts, totp
from tests.support.portal import FAST, ORIGIN, make_app, settings

pytestmark = pytest.mark.integration
PW = "violet-harbor-lantern-42"
NEW = "amber-meadow-kettle-77"
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def user(conn, clock, role, email=None, **kw):
    return accounts.create_user(
        conn,
        FAST,
        email=email or f"{role.lower()}@example.com",
        display_name="Test User",
        role=role,
        password=kw.pop("password", PW),
        now=clock.now(),
        **kw,
    )


def signed_in(app, email, password=PW, **extra):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": password, **extra})
    assert r.status_code == 200, r.text
    c.headers["x-csrf-token"] = c.cookies.get("csrf", "")
    return c, r.json()


def enrolled_admin(conn, app, clock, email="boss@example.com"):
    uid = user(conn, clock, "ADMIN", email)
    c, _ = signed_in(app, email)
    secret = c.post("/api/auth/mfa/enrol").json()["secret"]
    c.post(
        "/api/auth/mfa/confirm",
        json={"code": totp.code_at(secret, int(clock.now().timestamp()) // 30)},
    )
    return uid, secret


def test_every_route_except_the_public_ones_refuses_a_visitor_who_is_not_signed_in(env):
    _, app, _ = env
    c = TestClient(app)
    seen = set()
    for path, methods in app.openapi()["paths"].items():  # includes routes from included routers
        for method in (m.upper() for m in methods):
            key = (method, path)
            seen.add(key)
            url = path.replace("{session_id}", str(uuid4())).replace("{", "1").replace("}", "")
            r = c.request(method, url, json={} if method != "GET" else None)
            if key in security.PUBLIC:
                assert r.status_code != 401, key
            else:
                assert r.status_code == 401, f"{key} answered {r.status_code} to a visitor"
    assert security.PUBLIC <= seen
    # every route that changes something must be listed with an explicit permission, never left to the default
    for method, path in seen - security.PUBLIC:
        if method != "GET":
            assert (method, path) in security.ROUTE_PERMISSIONS, (
                f"{method} {path} has no declared permission"
            )
    assert set(security.ROUTE_PERMISSIONS) <= seen  # no stale entries


def test_the_health_check_stays_public_and_reveals_nothing_about_users(env):
    _, app, _ = env
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and set(r.json()) == {"api", "database", "redis"}


def test_a_suspended_user_is_locked_out_of_a_live_session_immediately(env):
    conn, app, clock = env
    uid = user(conn, clock, "VIEWER")
    c, _ = signed_in(app, "viewer@example.com")
    assert c.get("/api/auth/me").status_code == 200
    conn.execute("UPDATE portal_user SET status='SUSPENDED' WHERE user_id=%s", (uid,))
    assert c.get("/api/auth/me").status_code == 401
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"email": "viewer@example.com", "password": PW})
        .status_code
        == 401
    )


def test_each_role_reaches_only_what_the_matrix_allows(env):
    conn, app, clock = env
    user(conn, clock, "VIEWER")
    user(conn, clock, "TRADER")
    user(conn, clock, "OPERATOR", "ops@example.com")
    viewer, _ = signed_in(app, "viewer@example.com")
    trader, _ = signed_in(app, "trader@example.com")
    assert viewer.get("/api/instruments", params={"q": "x"}).status_code == 200  # research:read
    for c in (viewer, trader):
        assert c.get("/api/reviews").status_code == 403  # ops:read
        assert c.get("/api/system/activity").status_code == 403
        assert c.post("/api/reviews/x/decisions", json={}).status_code == 403  # ops:write
    # an operator must have a second factor before reaching anything, so they only see the enrolment gate here
    operator, _ = signed_in(app, "ops@example.com")
    assert operator.get("/api/reviews").json()["detail"] == "enrolment_required"
    secret = operator.post("/api/auth/mfa/enrol").json()["secret"]
    operator.post(
        "/api/auth/mfa/confirm",
        json={"code": totp.code_at(secret, int(clock.now().timestamp()) // 30)},
    )
    assert (
        operator.get("/api/reviews").status_code != 403
        and operator.get("/api/system/activity").status_code != 403
    )


def test_a_state_changing_request_needs_the_csrf_header_and_a_known_origin(env):
    conn, app, clock = env
    user(conn, clock, "TRADER")
    c, _ = signed_in(app, "trader@example.com")
    good = {"current": PW, "new": NEW}
    token = c.cookies.get("csrf")
    del c.headers["x-csrf-token"]
    assert c.post("/api/auth/password", json=good).status_code == 403  # cookie alone is not enough
    assert (
        c.post("/api/auth/password", json=good, headers={"x-csrf-token": "forged"}).status_code
        == 403
    )
    assert (
        c.post(
            "/api/auth/password",
            json=good,
            headers={"x-csrf-token": token, "origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/auth/password", json=good, headers={"x-csrf-token": token, "origin": ORIGIN}
        ).status_code
        == 200
    )
    assert c.get("/api/auth/me").status_code == 200  # reads need no token


def test_an_admin_without_a_second_factor_can_only_set_one_up(env):
    conn, app, clock = env
    user(conn, clock, "ADMIN", "boss@example.com")
    c, body = signed_in(app, "boss@example.com")
    assert body["user"]["enrolment_required"] is True
    blocked = c.get("/api/instruments", params={"q": "x"})
    assert blocked.status_code == 403 and blocked.json()["detail"] == "enrolment_required"
    assert c.get("/api/auth/sessions").status_code == 403  # even own-session pages wait
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/mfa/enrol").json()["uri"].startswith("otpauth://")
    assert c.post("/api/auth/mfa/confirm", json={"code": "000000"}).status_code == 422
    secret = c.post("/api/auth/mfa/enrol").json()["secret"]  # may restart before confirming
    ok = c.post(
        "/api/auth/mfa/confirm",
        json={"code": totp.code_at(secret, int(clock.now().timestamp()) // 30)},
    )
    assert ok.status_code == 200 and len(ok.json()["recovery_codes"]) == 10
    assert c.get("/api/instruments", params={"q": "x"}).status_code == 200  # unlocked at once
    assert c.post("/api/auth/mfa/enrol").status_code == 409  # already on


def test_a_temporary_password_must_be_replaced_before_anything_else(env):
    conn, app, clock = env
    user(conn, clock, "TRADER", must_change_password=True)
    c, body = signed_in(app, "trader@example.com")
    assert body["user"]["must_change_password"] is True
    blocked = c.get("/api/instruments", params={"q": "x"})
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    assert (
        c.post("/api/auth/password", json={"current": PW, "new": "short"}).status_code == 422
    )  # policy
    assert (
        c.post("/api/auth/password", json={"current": "not-my-password-1", "new": NEW}).status_code
        == 422
    )
    assert c.post("/api/auth/password", json={"current": PW, "new": NEW}).status_code == 200
    assert c.get("/api/instruments", params={"q": "x"}).status_code == 200


def test_the_client_address_comes_from_the_proxy_header_only_when_a_proxy_is_trusted(
    conn, pg_url, tmp_path
):
    migrate(conn)
    accounts.create_user(
        conn, FAST, email="a@example.com", display_name="A B", role="VIEWER", password=PW, now=START
    )

    ticks = iter(range(1, 10))

    def ip_after_login(
        trust, headers
    ):  # each call later than the last, so "the newest session" is unambiguous
        app = make_app(
            pg_url,
            tmp_path,
            portal=settings(SimClock(START + timedelta(minutes=next(ticks))), trust_proxy=trust),
        )
        TestClient(app).post(
            "/api/auth/login", json={"email": "a@example.com", "password": PW}, headers=headers
        )
        return conn.execute(
            "SELECT ip FROM portal_session ORDER BY created_at DESC, session_id LIMIT 1"
        ).fetchone()[0]

    spoof = {"x-forwarded-for": "9.9.9.9, 203.0.113.50"}  # the proxy appended the real client last
    assert ip_after_login(True, spoof) == "203.0.113.50"
    assert ip_after_login(False, spoof) == "testclient"  # an untrusted header is ignored
    assert (
        ip_after_login(True, {}) == "testclient"
    )  # trusted but absent: fall back to the connection


def test_a_connection_without_a_client_address_has_no_ip(env):
    from types import SimpleNamespace

    from starlette.requests import Request

    _, app, _ = env
    scope = {"type": "http", "headers": [], "client": None, "app": SimpleNamespace(state=app.state)}
    assert security.client_ip(Request(scope)) is None

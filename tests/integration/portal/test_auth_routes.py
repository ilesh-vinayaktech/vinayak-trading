from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from algo.api.security import PortalSettings
from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.portal import accounts, ratelimit, totp
from tests.support.portal import FAST, ORIGIN, RING, make_app, settings

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


def test_signing_in_sets_a_locked_down_cookie_and_returns_the_user_and_permissions(env):
    conn, app, clock = env
    user(conn, clock, "TRADER")
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "Trader@Example.com", "password": PW})
    assert r.status_code == 200
    u = r.json()["user"]
    assert (u["email"], u["role"], u["mfa_enabled"], u["enrolment_required"]) == (
        "trader@example.com",
        "TRADER",
        False,
        False,
    )
    assert "kite:own" in u["permissions"] and "users:write" not in u["permissions"]
    cookies = {h.split("=")[0]: h for h in r.headers.get_list("set-cookie")}
    assert (
        "HttpOnly" in cookies["session"]
        and "SameSite=lax" in cookies["session"]
        and "Path=/" in cookies["session"]
    )
    assert "HttpOnly" not in cookies["csrf"]  # the page must be able to read this one to echo it
    assert c.get("/api/auth/me").json()["user"]["email"] == "trader@example.com"


def test_a_secure_deployment_uses_the_host_prefixed_secure_cookie(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    app = make_app(
        pg_url, tmp_path, portal=PortalSettings(FAST, RING, clock, (ORIGIN,), cookie_secure=True)
    )
    accounts.create_user(
        conn, FAST, email="a@example.com", display_name="A B", role="VIEWER", password=PW, now=START
    )
    r = TestClient(app, base_url="https://testserver").post(
        "/api/auth/login", json={"email": "a@example.com", "password": PW}
    )
    first = r.headers.get_list("set-cookie")[0]
    assert first.startswith("__Host-session=") and "Secure" in first and "HttpOnly" in first


def test_bad_credentials_get_one_generic_answer_and_too_many_get_a_429(env):
    conn, app, clock = env
    user(conn, clock, "VIEWER")
    c = TestClient(app)
    bad = [
        c.post("/api/auth/login", json={"email": e, "password": "wrong-password-123"})
        for e in ("viewer@example.com", "ghost@example.com", "junk")
    ]
    assert {r.status_code for r in bad} == {401} and len(
        {r.text for r in bad}
    ) == 1  # indistinguishable
    for _ in range(4):
        c.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "wrong-password-123"},
        )
    blocked = c.post("/api/auth/login", json={"email": "viewer@example.com", "password": PW})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "900"
    clock.advance(ratelimit.WINDOW + timedelta(seconds=1))
    assert (
        c.post("/api/auth/login", json={"email": "viewer@example.com", "password": PW}).status_code
        == 200
    )
    assert (
        c.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "x" * 300}
        ).status_code
        == 422
    )  # bounded input


def test_logout_ends_the_session_on_the_server_not_just_in_the_browser(env):
    conn, app, clock = env
    user(conn, clock, "VIEWER")
    c, _ = signed_in(app, "viewer@example.com")
    stolen = c.cookies.get("session")
    assert c.post("/api/auth/logout").status_code == 200
    thief = TestClient(app)
    thief.cookies.set("session", stolen)
    assert thief.get("/api/auth/me").status_code == 401  # the copied cookie is dead


def test_login_with_a_second_factor_takes_the_code_in_a_second_step(env):
    conn, app, clock = env
    _, secret = enrolled_admin(conn, app, clock)
    clock.advance(timedelta(seconds=90))  # a fresh time step: the enrolment code is not replayed
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "boss@example.com", "password": PW}).json() == {
        "mfa_required": True
    }
    assert "session" not in c.cookies
    wrong = c.post(
        "/api/auth/login", json={"email": "boss@example.com", "password": PW, "totp_code": "000000"}
    )
    assert wrong.status_code == 401 and wrong.json()["detail"] == "That code is not valid."
    code = totp.code_at(secret, int(clock.now().timestamp()) // 30)
    ok = c.post(
        "/api/auth/login", json={"email": "boss@example.com", "password": PW, "totp_code": code}
    )
    assert ok.status_code == 200 and ok.json()["user"]["mfa_enabled"] is True


def test_users_can_list_and_end_their_own_sessions_but_not_anyone_elses(env):
    conn, app, clock = env
    user(conn, clock, "TRADER")
    user(conn, clock, "VIEWER")
    a, _ = signed_in(app, "trader@example.com")
    a2, _ = signed_in(app, "trader@example.com")
    b, _ = signed_in(app, "viewer@example.com")
    mine = a.get("/api/auth/sessions").json()["sessions"]
    assert len(mine) == 2 and [s["current"] for s in mine].count(True) == 1
    theirs = b.get("/api/auth/sessions").json()["sessions"][0]["session_id"]
    assert (
        a.delete(f"/api/auth/sessions/{theirs}").status_code == 404
    )  # looks exactly like a missing one
    other = next(s["session_id"] for s in mine if not s["current"])
    assert a.delete(f"/api/auth/sessions/{other}").status_code == 200
    assert a2.get("/api/auth/me").status_code == 401 and a.get("/api/auth/me").status_code == 200

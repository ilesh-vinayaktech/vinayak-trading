import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
KEY, SECRET, TOKEN = "abcd1234efgh5678", "zyxw9876vuts5432", "SUPER-SECRET-ACCESS-TOKEN"


def fake_kite(calls, ok=True):
    def http(method, url, headers, data=None):
        calls.append((method, url))
        if not ok:
            return 403, json.dumps(
                {
                    "status": "error",
                    "message": "Token is invalid or has expired.",
                    "error_type": "TokenException",
                }
            ).encode()
        return 200, json.dumps(
            {"status": "success", "data": {"access_token": TOKEN, "user_id": "AB1234"}}
        ).encode()

    return http


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock, calls = SimClock(START), []
    st = settings(clock)
    object.__setattr__(st, "kite_http", fake_kite(calls))
    object.__setattr__(st, "public_url", "https://portal.example")
    return conn, make_app(pg_url, tmp_path, portal=st), clock, calls


def state_of(login_url):
    return unquote(parse_qs(urlparse(login_url).query)["redirect_params"][0]).removeprefix("state=")


def test_only_roles_that_may_use_kite_reach_the_routes_and_only_an_admin_the_system_feed(env):
    conn, app, clock, _ = env
    for role in ("VIEWER", "TRADER"):
        add_user(conn, clock, role)
    add_user(conn, clock, "ADMIN", "boss@example.com")
    viewer, trader, boss = (
        sign_in(app, "viewer@example.com"),
        sign_in(app, "trader@example.com"),
        sign_in(app, "boss@example.com"),
    )
    enrol_second_factor(boss, clock)
    assert viewer.get("/api/kite/connection").status_code == 403
    assert (
        viewer.post(
            "/api/kite/credentials", json={"api_key": KEY, "api_secret": SECRET}
        ).status_code
        == 403
    )
    assert trader.get("/api/kite/connection").status_code == 200
    assert (
        trader.get("/api/kite/system").status_code == 403
        and trader.post("/api/kite/system", json={"enabled": True}).status_code == 403
    )
    assert boss.get("/api/kite/system").json() == {"feed": None}


def test_the_full_connect_flow_and_that_no_response_ever_contains_a_secret(env):
    conn, app, clock, calls = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    c = sign_in(app, "jane@example.com")
    assert c.get("/api/kite/connection").json()["state"] == "not_configured"
    assert (
        c.post("/api/kite/credentials", json={"api_key": "short", "api_secret": SECRET}).status_code
        == 422
    )
    assert c.post("/api/kite/connect/start").status_code == 409  # nothing saved yet
    responses = [c.post("/api/kite/credentials", json={"api_key": KEY, "api_secret": SECRET})]
    saved = c.get("/api/kite/connection")
    assert (
        saved.json()["state"] == "saved"
        and saved.json()["api_key_hint"] == "5678"
        and saved.json()["redirect_url"] == "https://portal.example/kite/callback"
    )
    start = c.post("/api/kite/connect/start")
    assert start.json()["login_url"].startswith(
        f"https://kite.zerodha.com/connect/login?v=3&api_key={KEY}"
    )
    state = state_of(start.json()["login_url"])
    assert (
        c.post(
            "/api/kite/connect/complete", json={"request_token": "REQ", "state": "wrong"}
        ).status_code
        == 422
    )
    done = c.post(
        "/api/kite/connect/complete", json={"request_token": "REQ", "state": state}
    )  # the wrong try did not spend the real state
    assert (
        done.status_code == 200
        and done.json() == {"kite_user": "AB1234"}
        and calls[0][1].endswith("/session/token")
    )
    after = c.get("/api/kite/connection")
    responses += [saved, done, after, c.get("/api/auth/me"), c.get("/api/auth/sessions")]
    assert after.json()["state"] == "connected" and after.json()["kite_user_id"] == "AB1234"
    blob = " ".join(r.text for r in responses)
    assert (
        SECRET not in blob and TOKEN not in blob and KEY not in blob
    )  # none of the secrets in any answer
    assert (
        c.post(
            "/api/kite/connect/complete", json={"request_token": "REQ", "state": state}
        ).status_code
        == 422
    )  # one use
    assert c.post("/api/kite/disconnect").json() == {"ok": True}
    assert c.get("/api/kite/connection").json()["state"] == "saved"
    assert c.post("/api/kite/credentials/remove").json() == {"ok": True} and c.post(
        "/api/kite/credentials/remove"
    ).json() == {"ok": False}
    assert c.get("/api/kite/connection").json()["state"] == "not_configured"


def test_when_kite_refuses_the_user_is_told_and_nothing_is_connected(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    st = settings(clock)
    object.__setattr__(st, "kite_http", fake_kite([], ok=False))
    app = make_app(pg_url, tmp_path, portal=st)
    add_user(conn, clock, "TRADER", "jane@example.com")
    c = sign_in(app, "jane@example.com")
    c.post("/api/kite/credentials", json={"api_key": KEY, "api_secret": SECRET})
    state = state_of(c.post("/api/kite/connect/start").json()["login_url"])
    r = c.post("/api/kite/connect/complete", json={"request_token": "REQ", "state": state})
    assert r.status_code == 422 and "Kite refused the login" in r.json()["detail"]
    assert c.get("/api/kite/connection").json()["state"] == "saved"
    assert conn.execute(
        "SELECT count(*) FROM portal_audit WHERE action='kite.connect_failed'"
    ).fetchone() == (1,)  # kept despite the refusal


def test_users_never_see_each_others_connections(env):
    conn, app, clock, _ = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "TRADER", "bob@example.com")
    jane, bob = sign_in(app, "jane@example.com"), sign_in(app, "bob@example.com")
    jane.post("/api/kite/credentials", json={"api_key": KEY, "api_secret": SECRET})
    assert bob.get("/api/kite/connection").json()["state"] == "not_configured"
    assert bob.post("/api/kite/connect/start").status_code == 409
    state = state_of(jane.post("/api/kite/connect/start").json()["login_url"])
    bob.post(
        "/api/kite/credentials", json={"api_key": "bobkey123456", "api_secret": "bobsecret1234"}
    )
    assert (
        bob.post(
            "/api/kite/connect/complete", json={"request_token": "REQ", "state": state}
        ).status_code
        == 422
    )  # jane's state is not his


def test_an_administrator_can_mark_their_own_connection_as_the_system_feed(env):
    conn, app, clock, _ = env
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    boss = sign_in(app, "boss@example.com")
    enrol_second_factor(boss, clock)
    assert (
        boss.post("/api/kite/system", json={"enabled": True}).status_code == 409
    )  # nothing saved yet
    boss.post("/api/kite/credentials", json={"api_key": KEY, "api_secret": SECRET})
    assert boss.post("/api/kite/system", json={"enabled": True}).json() == {"ok": True}
    feed = boss.get("/api/kite/system").json()["feed"]
    assert (feed["owner"], feed["state"], feed["api_key_hint"]) == ("The Boss", "saved", "5678")
    assert boss.get("/api/kite/connection").json()["is_system"] is True
    assert boss.post("/api/kite/system", json={"enabled": False}).json() == {"ok": True}
    assert boss.get("/api/kite/system").json() == {"feed": None}

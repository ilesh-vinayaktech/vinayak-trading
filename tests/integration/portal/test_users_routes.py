from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.portal.mailer import ConsoleMailer
from tests.support.portal import PW, add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
NEW = "amber-meadow-kettle-77"


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock, mail = SimClock(START), ConsoleMailer()
    st = settings(clock)
    object.__setattr__(
        st, "mailer", mail
    )  # the frozen settings object, given a mailer we can read back
    object.__setattr__(st, "public_url", "https://portal.example")
    return conn, make_app(pg_url, tmp_path, portal=st), clock, mail


def admin(conn, app, clock):
    add_user(conn, clock, "ADMIN", "boss@example.com", name="The Boss")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    return c


def test_only_an_administrator_can_see_or_change_users_and_read_the_audit_trail(env):
    conn, app, clock, _ = env
    for role in ("VIEWER", "TRADER", "OPERATOR"):
        add_user(conn, clock, role)
    boss = admin(conn, app, clock)
    some_id = str(uuid4())
    operator = sign_in(app, "operator@example.com")
    enrol_second_factor(operator, clock)  # an operator must have a second factor to use anything
    for who in ("viewer", "trader"):
        c = sign_in(app, f"{who}@example.com")
        assert c.get("/api/users").status_code == 403 and c.get("/api/audit").status_code == 403
        assert (
            c.post(
                "/api/users", json={"email": "x@example.com", "name": "X Y", "role": "VIEWER"}
            ).status_code
            == 403
        )
        assert c.post(f"/api/users/{some_id}/role", json={"role": "ADMIN"}).status_code == 403
    assert (
        operator.get("/api/users").status_code == 403
        and operator.get("/api/audit").status_code == 403
    )  # operators run ops, not accounts
    assert boss.get("/api/users").status_code == 200 and boss.get("/api/audit").status_code == 200


def test_the_directory_lists_filters_and_shows_a_profile(env):
    conn, app, clock, _ = env
    add_user(conn, clock, "TRADER", "tina@example.com", name="Tina Trader")
    boss = admin(conn, app, clock)
    listing = boss.get("/api/users", params={"q": "tina"}).json()
    assert listing["total"] == 1 and listing["items"][0]["email"] == "tina@example.com"
    assert boss.get("/api/users", params={"role": "ROOT"}).status_code == 422
    assert boss.get("/api/users", params={"limit": 1000}).status_code == 422  # bounded
    profile = boss.get(f"/api/users/{listing['items'][0]['id']}").json()
    assert (
        profile["name"] == "Tina Trader"
        and profile["status"] == "ACTIVE"
        and "password_hash" not in profile
    )
    assert boss.get(f"/api/users/{uuid4()}").status_code == 404
    assert boss.get("/api/users/not-a-uuid").status_code == 422


def test_inviting_someone_mails_a_link_that_lets_them_choose_a_password_once(env):
    conn, app, clock, mail = env
    boss = admin(conn, app, clock)
    r = boss.post(
        "/api/users", json={"email": "New@Example.com", "name": "New Hire", "role": "TRADER"}
    )
    assert r.status_code == 200 and r.json()["invite_url"].startswith(
        "https://portal.example/accept-invite?token="
    )
    assert mail.sent[-1].to == "new@example.com"
    token = r.json()["invite_url"].split("token=")[1]
    visitor = TestClient(app)
    assert (
        visitor.post(
            "/api/auth/login", json={"email": "new@example.com", "password": PW}
        ).status_code
        == 401
    )  # not active yet
    assert (
        visitor.post(
            "/api/auth/accept-invite", json={"token": token, "password": "short"}
        ).status_code
        == 422
    )
    assert (
        visitor.post("/api/auth/accept-invite", json={"token": token, "password": PW}).status_code
        == 422
    )  # the refused try spent the link
    fresh = (
        boss.post(f"/api/users/{r.json()['id']}/resend-invite")
        .json()["invite_url"]
        .split("token=")[1]
    )
    assert visitor.post(
        "/api/auth/accept-invite", json={"token": fresh, "password": PW}
    ).json() == {"ok": True}
    assert (
        visitor.post(
            "/api/auth/login", json={"email": "new@example.com", "password": PW}
        ).status_code
        == 200
    )
    assert (
        visitor.post("/api/auth/accept-invite", json={"token": fresh, "password": PW}).status_code
        == 422
    )  # one use only
    assert (
        boss.post(
            "/api/users", json={"email": "new@example.com", "name": "Dup", "role": "VIEWER"}
        ).status_code
        == 409
    )
    assert (
        boss.post(
            "/api/users", json={"email": "z@example.com", "name": "Z Z", "role": "ROOT"}
        ).status_code
        == 422
    )
    assert (
        boss.post(f"/api/users/{r.json()['id']}/resend-invite").status_code == 409
    )  # no longer pending


def test_an_administrator_manages_roles_status_names_sessions_and_second_factors(env):
    conn, app, clock, _ = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    boss = admin(conn, app, clock)
    janes_session = sign_in(app, "jane@example.com")
    assert boss.post(f"/api/users/{jane}/name", json={"name": "Jane Q. Roe"}).status_code == 200
    assert boss.post(f"/api/users/{jane}/name", json={"name": " "}).status_code == 422
    assert boss.post(f"/api/users/{jane}/role", json={"role": "VIEWER"}).status_code == 200
    assert janes_session.get("/api/auth/me").status_code == 401  # a role change ends the session
    assert boss.post(f"/api/users/{jane}/status", json={"status": "SUSPENDED"}).status_code == 200
    assert (
        TestClient(app)
        .post("/api/auth/login", json={"email": "jane@example.com", "password": PW})
        .status_code
        == 401
    )
    assert boss.post(f"/api/users/{jane}/status", json={"status": "ACTIVE"}).status_code == 200
    again = sign_in(app, "jane@example.com")
    assert (
        boss.post(f"/api/users/{jane}/end-sessions").json() == {"ended": 1}
        and again.get("/api/auth/me").status_code == 401
    )
    assert boss.post(f"/api/users/{jane}/reset-mfa").status_code == 200
    assert boss.post(f"/api/users/{uuid4()}/role", json={"role": "VIEWER"}).status_code == 404
    assert boss.post(f"/api/users/{uuid4()}/end-sessions").status_code == 404
    me = boss.get("/api/auth/me").json()["user"]["id"]
    for path, body in (
        (f"/api/users/{me}/role", {"role": "VIEWER"}),
        (f"/api/users/{me}/status", {"status": "DISABLED"}),
        (f"/api/users/{me}/reset-mfa", None),
    ):
        assert (
            boss.post(path, json=body).status_code == 409
        )  # not on yourself, and not the last administrator
    assert boss.post(f"/api/users/{jane}/status", json={"status": "INVITED"}).status_code == 422


def test_a_forgotten_password_is_reset_through_a_mailed_link_and_old_sessions_end(env):
    conn, app, clock, mail = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    old = sign_in(app, "jane@example.com")
    visitor = TestClient(app)
    answers = [
        visitor.post("/api/auth/forgot", json={"email": e})
        for e in ("jane@example.com", "ghost@example.com", "nonsense")
    ]
    assert {a.status_code for a in answers} == {200} and {a.text for a in answers} == {
        '{"ok":true}'
    }  # indistinguishable
    assert [m.to for m in mail.sent] == ["jane@example.com"]
    token = mail.sent[0].body.split("token=")[1]
    assert (
        visitor.post(
            "/api/auth/reset-password", json={"token": token, "password": "short"}
        ).status_code
        == 422
    )
    visitor.post("/api/auth/forgot", json={"email": "jane@example.com"})
    token = mail.sent[1].body.split("token=")[1]
    assert visitor.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW}
    ).json() == {"ok": True}
    assert old.get("/api/auth/me").status_code == 401
    assert (
        visitor.post(
            "/api/auth/login", json={"email": "jane@example.com", "password": NEW}
        ).status_code
        == 200
    )
    assert (
        visitor.post("/api/auth/reset-password", json={"token": token, "password": NEW}).status_code
        == 422
    )


def test_an_administrator_can_start_a_reset_for_an_active_account_only(env):
    conn, app, clock, mail = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com")
    boss = admin(conn, app, clock)
    r = boss.post(f"/api/users/{jane}/reset-password")
    assert (
        r.status_code == 200
        and r.json()["reset_url"].startswith("https://portal.example/reset-password?token=")
        and mail.sent[-1].to == "jane@example.com"
    )
    boss.post(f"/api/users/{jane}/status", json={"status": "DISABLED"})
    assert boss.post(f"/api/users/{jane}/reset-password").status_code == 409


def test_the_audit_feed_filters_and_records_who_did_what(env):
    conn, app, clock, _ = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com")
    boss = admin(conn, app, clock)
    boss.post(f"/api/users/{jane}/status", json={"status": "SUSPENDED"})
    events = boss.get(
        "/api/audit", params={"target_type": "user", "target_id": str(jane), "action": "user."}
    ).json()["events"]
    assert [e["action"] for e in events] == ["user.status_changed", "user.create"]
    assert (
        events[0]["detail"] == {"from": "ACTIVE", "to": "SUSPENDED", "sessions_ended": 0}
        and events[0]["actor_user_id"]
    )
    assert (
        boss.get("/api/audit", params={"actor_id": events[0]["actor_user_id"], "limit": 1}).json()[
            "events"
        ][0]["actor_user_id"]
        == events[0]["actor_user_id"]
    )
    assert boss.get("/api/audit", params={"limit": 500}).status_code == 422

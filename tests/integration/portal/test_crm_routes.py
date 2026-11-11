from datetime import UTC, datetime
from uuid import uuid4

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def staff_member(conn, app, clock, role="OPERATOR", email="ops@example.com", name="Olive Ops"):
    uid = add_user(conn, clock, role, email, name=name)
    c = sign_in(app, email)
    enrol_second_factor(c, clock)
    return uid, c


def test_only_staff_can_use_the_crm_and_it_never_reaches_traders_or_viewers(env):
    conn, app, clock = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    _, ops = staff_member(conn, app, clock)
    for who in ("jane@example.com", "viewer@example.com"):
        c = sign_in(app, who)
        for method, path, body in (
            ("GET", f"/api/users/{jane}/notes", None),
            ("POST", f"/api/users/{jane}/notes", {"body": "x"}),
            ("POST", f"/api/users/{jane}/tags", {"tag": "x"}),
            ("GET", "/api/tags", None),
            ("GET", "/api/staff", None),
            ("GET", "/api/tasks", None),
            ("POST", "/api/tasks", {"title": "t", "owner_id": str(jane)}),
        ):
            assert c.request(method, path, json=body).status_code == 403, (who, method, path)
    assert (
        ops.get("/api/tags").status_code == 200
        and ops.get(f"/api/users/{jane}/notes").status_code == 200
    )


def test_notes_and_tags_flow_and_the_directory_can_be_filtered_and_shows_tags(env):
    conn, app, clock = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    add_user(conn, clock, "TRADER", "bob@example.com", name="Bob Roe")
    _, boss = staff_member(conn, app, clock, "ADMIN", "boss@example.com", "The Boss")
    assert (
        boss.post(f"/api/users/{jane}/notes", json={"body": "Asked about Kite"}).status_code == 200
    )
    assert boss.post(f"/api/users/{jane}/notes", json={"body": " "}).status_code == 422
    assert [n["body"] for n in boss.get(f"/api/users/{jane}/notes").json()["notes"]] == [
        "Asked about Kite"
    ]
    assert boss.get(f"/api/users/{uuid4()}/notes").status_code == 404
    assert boss.post(f"/api/users/{jane}/tags", json={"tag": " KYC Pending "}).json() == {
        "tag": "kyc pending"
    }
    assert boss.post(f"/api/users/{jane}/tags", json={"tag": "bad!"}).status_code == 422
    assert boss.get("/api/tags").json() == {"tags": [{"tag": "kyc pending", "users": 1}]}
    listing = boss.get("/api/users", params={"tag": "KYC Pending"}).json()
    assert [u["email"] for u in listing["items"]] == ["jane@example.com"] and listing["items"][0][
        "tags"
    ] == ["kyc pending"]
    assert boss.get(f"/api/users/{jane}").json()["tags"] == ["kyc pending"]
    assert {u["email"]: u["tags"] for u in boss.get("/api/users").json()["items"]}[
        "bob@example.com"
    ] == []
    assert boss.post(f"/api/users/{jane}/tags/remove", json={"tag": "kyc pending"}).json() == {
        "ok": True
    }
    assert boss.post(f"/api/users/{jane}/tags/remove", json={"tag": "kyc pending"}).json() == {
        "ok": False
    }
    assert boss.get("/api/users", params={"tag": "kyc pending"}).json()["total"] == 0
    assert boss.post(f"/api/users/{jane}/tags/remove", json={"tag": "bad!"}).status_code == 422


def test_tasks_are_created_listed_filtered_and_completed_and_staff_are_listed_for_assignment(env):
    conn, app, clock = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com")
    ops_id, ops = staff_member(conn, app, clock)
    _, boss = staff_member(conn, app, clock, "ADMIN", "boss@example.com", "The Boss")
    assert [s["name"] for s in boss.get("/api/staff").json()["staff"]] == [
        "Olive Ops",
        "The Boss",
    ]  # not Jane
    made = boss.post(
        "/api/tasks",
        json={
            "title": "Call Jane",
            "detail": "about Kite",
            "owner_id": str(ops_id),
            "user_id": str(jane),
            "due_date": "2026-11-15",
        },
    )
    assert made.status_code == 200
    assert (
        boss.post("/api/tasks", json={"title": "x", "owner_id": str(jane)}).status_code == 422
    )  # not staff
    assert boss.post("/api/tasks", json={"title": "", "owner_id": str(ops_id)}).status_code == 422
    assert (
        boss.post(
            "/api/tasks", json={"title": "x", "owner_id": str(ops_id), "user_id": str(uuid4())}
        ).status_code
        == 404
    )
    assert (
        boss.post(
            "/api/tasks", json={"title": "x", "owner_id": str(ops_id), "due_date": "not-a-date"}
        ).status_code
        == 422
    )
    mine = ops.get("/api/tasks", params={"mine": "true", "status": "OPEN"}).json()["tasks"]
    assert [t["title"] for t in mine] == ["Call Jane"] and mine[0]["about_id"] == str(jane)
    assert boss.get("/api/tasks", params={"mine": "true"}).json()["tasks"] == []
    assert (
        boss.get("/api/tasks", params={"user_id": str(jane)}).json()["tasks"][0]["due_date"]
        == "2026-11-15"
    )
    assert boss.get("/api/tasks", params={"status": "WAT"}).status_code == 422
    tid = made.json()["id"]
    assert ops.post(f"/api/tasks/{tid}/status", json={"status": "DONE"}).json() == {"ok": True}
    assert boss.get("/api/tasks", params={"status": "DONE"}).json()["tasks"][0]["completed_at"]
    assert ops.post(f"/api/tasks/{tid}/status", json={"status": "WAT"}).status_code == 422
    assert ops.post(f"/api/tasks/{uuid4()}/status", json={"status": "DONE"}).status_code == 404

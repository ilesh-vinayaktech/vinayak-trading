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


def operator(conn, app, clock):
    uid = add_user(conn, clock, "OPERATOR", "ops@example.com", name="Olive Ops")
    c = sign_in(app, "ops@example.com")
    enrol_second_factor(c, clock)
    return uid, c


def raise_ticket(client, subject="Cannot connect Kite", body="Invalid token", priority="NORMAL"):
    r = client.post("/api/tickets", json={"subject": subject, "body": body, "priority": priority})
    assert r.status_code == 200, r.text
    listing = client.get("/api/tickets").json()["items"]
    return next(t["id"] for t in listing if t["number"] == r.json()["number"])


def test_every_signed_in_role_can_raise_and_read_their_own_tickets(env):
    conn, app, clock = env
    for role in ("VIEWER", "TRADER"):
        add_user(conn, clock, role)
    for who in ("viewer@example.com", "trader@example.com"):
        c = sign_in(app, who)
        tid = raise_ticket(c, subject=f"From {who}")
        t = c.get(f"/api/tickets/{tid}").json()
        assert t["status"] == "OPEN" and [m["body"] for m in t["messages"]] == ["Invalid token"]
        assert [x["subject"] for x in c.get("/api/tickets").json()["items"]] == [
            f"From {who}"
        ]  # only their own


def test_people_cannot_reach_each_others_tickets_and_the_answer_is_always_not_found(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "TRADER", "bob@example.com")
    jane, bob = sign_in(app, "jane@example.com"), sign_in(app, "bob@example.com")
    tid = raise_ticket(jane)
    for method, path, body in (
        ("GET", f"/api/tickets/{tid}", None),
        ("POST", f"/api/tickets/{tid}/messages", {"body": "hi"}),
        ("POST", f"/api/tickets/{tid}/status", {"status": "CLOSED"}),
    ):
        assert bob.request(method, path, json=body).status_code == 404, (method, path)
    assert bob.get(f"/api/tickets/{uuid4()}").status_code == 404
    assert (
        bob.post(f"/api/tickets/{tid}/assign", json={}).status_code == 403
    )  # assigning is a staff permission
    assert bob.get("/api/tickets/not-a-uuid").status_code == 422


def test_a_support_conversation_between_a_trader_and_an_operator(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    ops_id, ops = operator(conn, app, clock)
    jane = sign_in(app, "jane@example.com")
    tid = raise_ticket(jane, priority="HIGH")
    queue = ops.get("/api/tickets", params={"status": "OPEN"}).json()
    assert (
        queue["total"] == 1
        and queue["items"][0]["requester"] == "Test User"
        and queue["items"][0]["priority"] == "HIGH"
    )
    assert (
        ops.post(f"/api/tickets/{tid}/messages", json={"body": "Which browser?"}).status_code == 200
    )
    assert (
        ops.post(
            f"/api/tickets/{tid}/messages", json={"body": "Check token expiry", "internal": True}
        ).status_code
        == 200
    )
    assert (
        ops.post(f"/api/tickets/{tid}/assign", json={"assignee_id": str(ops_id)}).status_code == 200
    )
    seen = jane.get(f"/api/tickets/{tid}").json()
    assert (
        seen["status"] == "PENDING"
        and seen["assignee"] == "Olive Ops"
        and [m["body"] for m in seen["messages"]] == ["Invalid token", "Which browser?"]
    )
    assert (
        "Check token expiry" not in jane.get(f"/api/tickets/{tid}").text
    )  # internal notes never reach the requester
    assert (
        jane.post(f"/api/tickets/{tid}/messages", json={"body": "x", "internal": True}).status_code
        == 403
    )
    assert jane.post(f"/api/tickets/{tid}/messages", json={"body": "Firefox"}).status_code == 200
    assert jane.get(f"/api/tickets/{tid}").json()["status"] == "OPEN"
    assert jane.post(f"/api/tickets/{tid}/status", json={"status": "RESOLVED"}).status_code == 403
    assert ops.post(f"/api/tickets/{tid}/status", json={"status": "RESOLVED"}).status_code == 200
    assert jane.post(f"/api/tickets/{tid}/status", json={"status": "CLOSED"}).status_code == 200
    assert jane.post(f"/api/tickets/{tid}/messages", json={"body": "more"}).status_code == 409
    assert (
        ops.get("/api/tickets", params={"assignee_id": str(ops_id), "status": "CLOSED"}).json()[
            "total"
        ]
        == 1
    )
    assert ops.get("/api/tickets", params={"mine": "true"}).json()["total"] == 0


def test_inputs_are_validated_and_bounded(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    _, ops = operator(conn, app, clock)
    jane = sign_in(app, "jane@example.com")
    assert jane.post("/api/tickets", json={"subject": " ", "body": "x"}).status_code == 422
    assert (
        jane.post(
            "/api/tickets", json={"subject": "s", "body": "b", "priority": "URGENT"}
        ).status_code
        == 422
    )
    assert jane.post("/api/tickets", json={"subject": "s" * 301, "body": "b"}).status_code == 422
    assert jane.get("/api/tickets", params={"limit": 1000}).status_code == 422
    assert jane.get("/api/tickets", params={"status": "WAT"}).status_code == 422
    tid = raise_ticket(jane)
    assert ops.post(f"/api/tickets/{tid}/status", json={"status": "WAT"}).status_code == 422
    assert (
        ops.post(f"/api/tickets/{tid}/assign", json={"assignee_id": str(uuid4())}).status_code
        == 422
    )
    assert ops.post(f"/api/tickets/{tid}/assign", json={"assignee_id": None}).status_code == 200

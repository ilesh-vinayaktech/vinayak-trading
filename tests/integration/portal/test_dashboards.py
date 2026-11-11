from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.live.bar_store import save_status
from algo.portal import kite_vault
from tests.support.portal import (
    RING,
    add_user,
    enrol_second_factor,
    make_app,
    settings,
    sign_in,
)

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def staff(conn, app, clock, role="OPERATOR", email="ops@example.com"):
    uid = add_user(conn, clock, role, email, name="Olive Ops")
    c = sign_in(app, email)
    enrol_second_factor(c, clock)
    return uid, c


def test_my_dashboard_shows_only_my_own_kite_tickets_tasks_and_security(env):
    conn, app, clock = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    add_user(conn, clock, "TRADER", "bob@example.com", name="Bob Roe")
    ops_id, ops = staff(conn, app, clock)
    jc, bc = sign_in(app, "jane@example.com"), sign_in(app, "bob@example.com")
    assert jc.post("/api/tickets", json={"subject": "Help", "body": "x"}).status_code == 200
    assert bc.post("/api/tickets", json={"subject": "Bob only", "body": "x"}).status_code == 200
    ops.post(
        "/api/tasks",
        json={
            "title": "Late",
            "owner_id": str(ops_id),
            "user_id": str(jane),
            "due_date": "2026-11-01",
        },
    )
    ops.post("/api/tasks", json={"title": "Not late", "owner_id": str(ops_id)})

    me = jc.get("/api/dashboard/me").json()
    assert me["kite"]["state"] == "not_configured"
    assert me["tickets"]["open"] == 1
    assert [t["subject"] for t in me["tickets"]["latest"]] == ["Help"]
    assert me["tasks"] == {"open": 0, "overdue": 0}  # follow-ups belong to staff, not to Jane
    assert ops.get("/api/dashboard/me").json()["tasks"] == {"open": 2, "overdue": 1}
    assert me["security"]["mfa_enabled"] is False
    assert me["security"]["active_sessions"] == 1

    kite_vault.save_credentials(
        conn, RING, user_id=jane, api_key="k" * 16, api_secret="s" * 16, now=clock.now()
    )
    saved = jc.get("/api/dashboard/me").json()["kite"]
    assert saved["state"] == "saved" and "k" * 16 not in str(saved)


def test_operations_dashboard_counts_users_signins_tickets_tasks_feed_and_recent_events(env):
    conn, app, clock = env
    jane = add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    add_user(conn, clock, "VIEWER", "v@example.com")
    ops_id, ops = staff(conn, app, clock)
    bad = TestClient(app).post(
        "/api/auth/login", json={"email": "v@example.com", "password": "nope-nope-nope-1"}
    )
    assert bad.status_code in (400, 401)
    jc = sign_in(app, "jane@example.com")
    jc.post("/api/tickets", json={"subject": "Help", "body": "x"})
    for title, due in (("Late", "2026-11-01"), ("Later", "2027-01-01")):
        ops.post("/api/tasks", json={"title": title, "owner_id": str(ops_id), "due_date": due})

    d = ops.get("/api/dashboard/operations").json()
    assert d["users"]["by_role"] == {"OPERATOR": 1, "TRADER": 1, "VIEWER": 1}
    assert d["users"]["by_status"] == {"ACTIVE": 3}
    assert d["signins"]["failures_24h"] == 1 and d["signins"]["successes_24h"] >= 2
    assert d["tickets"] == {"open": 1, "unassigned": 1}
    assert d["tasks"] == {"open": 2, "overdue": 1}
    assert d["kite"] == {"connected": 0, "feed": None}
    assert d["recent"] and {"at", "actor", "action"} <= d["recent"][0].keys()

    kite_vault.save_credentials(
        conn, RING, user_id=jane, api_key="k" * 16, api_secret="s" * 16, now=clock.now()
    )
    conn.execute(
        "UPDATE portal_kite_connection SET access_token_enc='x', token_expires_at=%s, is_system=true",
        (clock.now() + timedelta(hours=3),),
    )
    conn.commit()
    d = ops.get("/api/dashboard/operations").json()
    assert d["kite"]["connected"] == 1
    assert d["kite"]["feed"]["owner"] == "Jane Roe" and d["kite"]["feed"]["state"] == "connected"
    assert "k" * 16 not in str(d)


def test_operations_dashboard_reports_the_live_feed_with_its_heartbeat_and_tick_age(env):
    conn, app, clock = env
    _, ops = staff(conn, app, clock)
    assert ops.get("/api/dashboard/operations").json()["feed"] is None
    now = clock.now()
    save_status(
        conn, "CONNECTED", "497 instruments", subscribed=497, ticks=9, bars=2, bad_frames=0,
        late_ticks=0, last_tick_at=now - timedelta(seconds=3), last_bar_at=None, now=now - timedelta(seconds=10),
    )  # fmt: skip
    assert ops.get("/api/dashboard/operations").json()["feed"] == {
        "state": "CONNECTED", "detail": "497 instruments", "subscribed": 497, "heartbeat_age": 10, "tick_age": 3,
    }  # fmt: skip
    save_status(
        conn, "STOPPED", "stopped", subscribed=497, ticks=0, bars=0, bad_frames=0, late_ticks=0,
        last_tick_at=None, last_bar_at=None, now=now,
    )  # fmt: skip
    assert ops.get("/api/dashboard/operations").json()["feed"]["tick_age"] is None

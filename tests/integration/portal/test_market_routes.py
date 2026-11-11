from datetime import UTC, datetime

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)  # Thursday


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def staff(conn, app, clock, role="OPERATOR", email="ops@example.com"):
    add_user(conn, clock, role, email, name="Olive Ops")
    c = sign_in(app, email)
    enrol_second_factor(c, clock)
    return c


def test_only_staff_can_see_or_change_the_trading_calendar(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    body = {"day": "2026-11-14", "start": "09:15", "end": "10:00", "note": "x"}
    for who in ("jane@example.com", "viewer@example.com"):
        c = sign_in(app, who)
        assert c.get("/api/market/calendar").status_code == 403
        assert c.post("/api/market/sessions", json=body).status_code == 403
        assert c.post("/api/market/sessions/1/remove").status_code == 403
    assert staff(conn, app, clock).get("/api/market/calendar").status_code == 200


def test_the_calendar_shows_todays_windows_and_the_upcoming_exceptions(env):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    d = ops.get("/api/market/calendar").json()
    assert d["today"] == {"day": "2026-11-12", "windows": [{"start": "09:15", "end": "15:30"}]}
    assert d["exceptions"] == []
    r = ops.post(
        "/api/market/sessions",
        json={
            "day": "2026-11-14",
            "start": "09:15",
            "end": "10:00",
            "note": "  Special live session ",
        },
    )
    assert r.status_code == 200
    (row,) = ops.get("/api/market/calendar").json()["exceptions"]
    assert row == {
        "id": r.json()["id"],
        "day": "2026-11-14",
        "kind": "SESSION",
        "start": "09:15",
        "end": "10:00",
        "note": "Special live session",
        "source": "manual",
        "needs_times": False,
    }
    conn.execute(
        "INSERT INTO market_session (session_date, kind, note, source, created_at) VALUES ('2026-11-20','CLOSED','Holiday*','nse',%s)",
        (START,),
    )
    rows = ops.get("/api/market/calendar").json()["exceptions"]
    assert [(x["day"], x["kind"], x["start"], x["needs_times"]) for x in rows] == [
        ("2026-11-14", "SESSION", "09:15", False),
        ("2026-11-20", "CLOSED", None, True),
    ]


def test_bad_sessions_are_refused_with_a_reason_and_a_session_for_today_replaces_todays_rule(env):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    ok = {"day": "2026-11-14", "start": "09:15", "end": "10:00", "note": ""}
    assert ops.post("/api/market/sessions", json=ok).status_code == 200
    bad = {
        "end before start": {**ok, "start": "11:00", "end": "10:00"},
        "overlap": {**ok, "start": "09:30", "end": "10:30"},
        "past day": {**ok, "day": "2026-11-11"},
    }
    for why, body in bad.items():
        r = ops.post("/api/market/sessions", json=body)
        assert r.status_code == 400 and r.json()["detail"], why
    assert ops.post("/api/market/sessions", json={**ok, "start": "nine"}).status_code == 422
    today = {"day": "2026-11-12", "start": "18:15", "end": "19:15", "note": "Muhurat"}
    assert ops.post("/api/market/sessions", json=today).status_code == 200
    windows = ops.get("/api/market/calendar").json()["today"]["windows"]
    assert windows == [{"start": "18:15", "end": "19:15"}]


def test_an_entry_can_be_removed_and_every_change_is_in_the_audit_log(env):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    body = {"day": "2026-11-14", "start": "09:15", "end": "10:00", "note": "x"}
    sid = ops.post("/api/market/sessions", json=body).json()["id"]
    assert ops.post(f"/api/market/sessions/{sid}/remove").status_code == 200
    assert ops.get("/api/market/calendar").json()["exceptions"] == []
    assert ops.post(f"/api/market/sessions/{sid}/remove").status_code == 404
    actions = [
        r[0]
        for r in conn.execute(
            "SELECT action FROM portal_audit WHERE action LIKE 'market.%' ORDER BY audit_id"
        )
    ]
    assert actions == ["market.session_added", "market.session_removed"]
    added = conn.execute(
        "SELECT actor_label, detail FROM portal_audit WHERE action='market.session_added'"
    ).fetchone()
    assert added[0] == "ops@example.com" and added[1]["day"] == "2026-11-14"

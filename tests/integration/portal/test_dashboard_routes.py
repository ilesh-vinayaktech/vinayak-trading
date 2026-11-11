from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from tests.support.portal import (
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


def test_everyone_gets_their_own_dashboard_and_only_staff_get_the_operations_one(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com", name="Jane Roe")
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    for who in ("jane@example.com", "viewer@example.com"):
        c = sign_in(app, who)
        assert c.get("/api/dashboard/me").status_code == 200
        assert c.get("/api/dashboard/operations").status_code == 403
    assert TestClient(app).get("/api/dashboard/me").status_code == 401
    _, ops = staff(conn, app, clock)
    assert ops.get("/api/dashboard/operations").status_code == 200

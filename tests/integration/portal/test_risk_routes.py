"""The risk page's API: the kill switch (own strategy for a trader, everyone for an operator) and the account's limits."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.paper import book
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def trader(conn, app, clock, email="jane@example.com", account=True):
    uid = add_user(conn, clock, "TRADER", email)
    if account:
        book.create_account(
            conn,
            uid,
            strategy_id="trend_pullback",
            params={},
            initial_cash=D(100000),
            started_on=date(2026, 11, 2),
            now=START,
        )
    return uid, sign_in(app, email)


def operator(conn, app, clock):
    add_user(conn, clock, "OPERATOR", "ops@example.com")
    c = sign_in(app, "ops@example.com")
    enrol_second_factor(c, clock)
    return c


def audit_actions(conn, like):
    return [
        r[0]
        for r in conn.execute(
            "SELECT action FROM portal_audit WHERE action LIKE %s ORDER BY audit_id", (like,)
        )
    ]


def test_anyone_signed_in_can_look_but_only_traders_and_operators_can_change(env):
    conn, app, clock = env
    add_user(conn, clock, "VIEWER", "viewer@example.com")
    viewer = sign_in(app, "viewer@example.com")
    assert (
        viewer.get("/api/risk").status_code == 200
    )  # the switch's state is visible to everyone who can see research
    for method, path in (
        ("PUT", "/api/risk/limits"),
        ("POST", "/api/risk/switch"),
        ("POST", "/api/risk/switch/global"),
    ):
        assert viewer.request(method, path, json={}).status_code == 403, path
    for method, path in (
        ("GET", "/api/risk"),
        ("PUT", "/api/risk/limits"),
        ("POST", "/api/risk/switch"),
        ("POST", "/api/risk/switch/global"),
    ):
        assert (
            TestClient(app).request(method, path, json=None if method == "GET" else {}).status_code
            == 401
        ), path


def test_a_fresh_account_is_running_with_no_limits_and_lists_what_can_be_limited(env):
    conn, app, clock = env
    _, c = trader(conn, app, clock)
    d = c.get("/api/risk").json()
    assert (
        d["account"] == {"strategy_id": "trend_pullback"}
        and d["limits"] == {}
        and d["events"] == []
    )
    assert (
        d["switch"] == {"effective": "RUNNING", "global": None, "strategy": None}
        and d["can_global"] is False
    )
    keys = {k["key"] for k in d["limit_keys"]}
    assert {
        "max_order_value",
        "max_open_orders",
        "trading_hours",
        "max_daily_loss",
        "check_margin",
    } <= keys


def test_a_trader_can_pause_cancel_and_resume_their_own_strategy_and_it_is_recorded(env):
    conn, app, clock = env
    _, c = trader(conn, app, clock)
    r = c.post("/api/risk/switch", json={"action": "pause", "reason": "looking at the data"})
    assert r.status_code == 200 and r.json()["effective"] == "PAUSE"
    d = c.get("/api/risk").json()
    assert d["switch"]["effective"] == "PAUSE" and d["switch"]["strategy"]["mode"] == "PAUSE"
    assert (d["events"][0]["by"], d["events"][0]["reason"], d["events"][0]["mode"]) == (
        "jane@example.com",
        "looking at the data",
        "PAUSE",
    )
    assert (
        c.post("/api/risk/switch", json={"action": "cancel", "reason": "bad fills"}).json()[
            "effective"
        ]
        == "CANCEL"
    )
    assert (
        c.post("/api/risk/switch", json={"action": "resume", "reason": "ok"}).json()["effective"]
        == "RUNNING"
    )
    assert [e["mode"] for e in c.get("/api/risk").json()["events"]] == [
        "RUNNING",
        "CANCEL",
        "PAUSE",
    ]  # newest first
    assert audit_actions(conn, "risk.%") == ["risk.switch_changed"] * 3


def test_a_reason_is_required_and_flatten_needs_the_emergency_override(env):
    conn, app, clock = env
    _, c = trader(conn, app, clock)
    assert c.post("/api/risk/switch", json={"action": "pause", "reason": "  "}).status_code == 422
    assert c.post("/api/risk/switch", json={"action": "explode", "reason": "x"}).status_code == 422
    refused = c.post("/api/risk/switch", json={"action": "flatten", "reason": "fire"})
    assert refused.status_code == 400 and "override" in refused.json()["detail"]
    assert c.get("/api/risk").json()["switch"]["effective"] == "RUNNING"
    ok = c.post(
        "/api/risk/switch", json={"action": "flatten", "reason": "fire", "emergency_override": True}
    )
    assert ok.json()["effective"] == "FLATTEN"


def test_without_a_paper_account_there_is_no_strategy_to_switch_but_the_page_still_loads(env):
    conn, app, clock = env
    _, c = trader(conn, app, clock, account=False)
    d = c.get("/api/risk").json()
    assert d["account"] is None and d["limits"] is None and d["switch"]["effective"] == "RUNNING"
    assert c.post("/api/risk/switch", json={"action": "pause", "reason": "x"}).status_code == 404
    assert c.put("/api/risk/limits", json={"limits": {}}).status_code == 404


def test_only_an_operator_can_switch_everyone_and_a_trader_sees_it(env):
    conn, app, clock = env
    _, jane = trader(conn, app, clock)
    assert (
        jane.post("/api/risk/switch/global", json={"action": "pause", "reason": "x"}).status_code
        == 403
    )
    ops = operator(conn, app, clock)
    assert (
        ops.post(
            "/api/risk/switch/global", json={"action": "pause", "reason": "exchange problem"}
        ).json()["effective"]
        == "PAUSE"
    )
    d = jane.get("/api/risk").json()
    assert (
        d["switch"]["effective"] == "PAUSE"
        and d["switch"]["global"]["reason"] == "exchange problem"
        and d["switch"]["strategy"] is None
    )
    assert ops.get("/api/risk").json()["can_global"] is True
    ops.post("/api/risk/switch/global", json={"action": "resume", "reason": "fixed"})
    assert jane.get("/api/risk").json()["switch"]["effective"] == "RUNNING"


def test_limits_are_validated_stored_shown_and_cleared(env):
    conn, app, clock = env
    _, c = trader(conn, app, clock)
    limits = {"max_order_value": "50000", "max_open_orders": 5, "trading_hours": ["09:15", "15:30"]}
    assert c.put("/api/risk/limits", json={"limits": limits}).json() == {"limits": limits}
    assert c.get("/api/risk").json()["limits"] == limits
    bad = c.put("/api/risk/limits", json={"limits": {"max_order_valu": 1}})
    assert bad.status_code == 422 and "unknown limit" in bad.json()["detail"]
    assert c.get("/api/risk").json()["limits"] == limits  # the bad update changed nothing
    assert (
        c.put("/api/risk/limits", json={"limits": {"max_open_orders": "many"}}).status_code == 422
    )
    assert c.put("/api/risk/limits", json={"limits": {}}).json() == {
        "limits": {}
    }  # empty clears them
    assert c.get("/api/risk").json()["limits"] == {}
    assert audit_actions(conn, "risk.limits%") == ["risk.limits_changed", "risk.limits_changed"]

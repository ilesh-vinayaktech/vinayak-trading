# ruff: noqa: E501
"""The regulatory page API: what is recorded, what blocks live trading, record a rule, re-verify it. Staff only to change."""

from datetime import UTC, date, datetime

import pytest

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.execution.regulatory import REQUIRED, Item, record
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
BODY = {
    "topic": "ops_limit",
    "value": {"orders_per_second": 10},
    "source": "NSE circular 123 of 2025-04-01",
    "effective_from": "2025-10-01",
}


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def staff(conn, app, clock):
    add_user(conn, clock, "OPERATOR", "ops@example.com", name="Olive Ops")
    c = sign_in(app, "ops@example.com")
    enrol_second_factor(c, clock)
    return c


def by_topic(c):
    return {i["topic"]: i for i in c.get("/api/regulatory").json()["items"]}


def old_row(conn, topic, verified):
    record(
        conn,
        Item(
            "NSE",
            "CM",
            topic,
            {"orders_per_second": 10},
            date(2025, 10, 1),
            "circular",
            verified,
            "owner",
        ),
    )


def test_nothing_recorded_means_every_rule_is_missing_and_live_is_blocked(env):
    conn, app, clock = env
    d = staff(conn, app, clock).get("/api/regulatory").json()
    assert d["blocks_live"] is True and d["max_age_days"] == 30
    assert [i["topic"] for i in d["items"]] == list(REQUIRED)
    assert {i["status"] for i in d["items"]} == {"missing"}
    assert all(i["label"] and i["help"] and i["example"] for i in d["items"])
    assert len(d["problems"]) == len(REQUIRED)


def test_only_staff_can_record_or_verify_but_a_trader_may_look(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    c = sign_in(app, "jane@example.com")
    assert c.get("/api/regulatory").status_code == 200
    assert c.post("/api/regulatory", json=BODY).status_code == 403
    assert c.post("/api/regulatory/ops_limit/verify").status_code == 403


def test_recording_a_rule_stores_who_and_when_and_unblocks_it(env):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    assert ops.post("/api/regulatory", json=BODY).status_code == 200
    i = by_topic(ops)["ops_limit"]
    assert (i["status"], i["value"], i["source"], i["effective_from"]) == (
        "ok",
        {"orders_per_second": 10},
        BODY["source"],
        "2025-10-01",
    )
    assert (i["last_verified"], i["verified_by"], i["expires_on"]) == (
        "2026-11-17",
        "ops@example.com",
        "2026-12-17",
    )
    d = ops.get("/api/regulatory").json()
    assert (
        d["blocks_live"] is True and len(d["problems"]) == len(REQUIRED) - 1
    )  # the others are still missing
    n = conn.execute(
        "SELECT count(*) FROM portal_audit WHERE action='regulatory.recorded'"
    ).fetchone()[0]
    assert n == 1


def test_all_four_recorded_unblocks_live(env):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    for t in REQUIRED:
        assert ops.post("/api/regulatory", json={**BODY, "topic": t}).status_code == 200
    d = ops.get("/api/regulatory").json()
    assert d["blocks_live"] is False and d["problems"] == []


def test_a_rule_last_verified_over_30_days_ago_is_stale_and_blocks(env):
    conn, app, clock = env
    for t in REQUIRED:
        old_row(conn, t, date(2026, 10, 1))
    ops = staff(conn, app, clock)
    d = ops.get("/api/regulatory").json()
    assert d["blocks_live"] is True and {i["status"] for i in d["items"]} == {"stale"}
    assert by_topic(ops)["ops_limit"]["expires_on"] == "2026-10-31"


def test_verify_again_keeps_the_value_and_moves_the_date(env):
    conn, app, clock = env
    old_row(conn, "ops_limit", date(2026, 10, 1))
    ops = staff(conn, app, clock)
    assert ops.post("/api/regulatory/ops_limit/verify").status_code == 200
    i = by_topic(ops)["ops_limit"]
    assert (
        i["value"] == {"orders_per_second": 10}
        and i["last_verified"] == "2026-11-17"
        and i["status"] == "ok"
    )
    assert conn.execute("SELECT count(*) FROM regulatory_config").fetchone()[0] == 2  # history kept
    assert ops.post("/api/regulatory/tagging/verify").status_code == 404  # nothing to re-check
    assert ops.post("/api/regulatory/nonsense/verify").status_code == 422
    n = conn.execute(
        "SELECT count(*) FROM portal_audit WHERE action='regulatory.verified'"
    ).fetchone()[0]
    assert n == 1


@pytest.mark.parametrize(
    "change",
    [
        {"topic": "nonsense"},
        {"source": "   "},
        {"value": None},
        {"value": {"orders_per_second_limit": "<fill in>"}},  # the template, not filled
        {"effective_from": "2026-11-18"},  # not in force yet: the check would say "not recorded"
        {"effective_from": "not-a-date"},
    ],
)
def test_a_bad_record_is_refused_and_nothing_is_stored(env, change):
    conn, app, clock = env
    ops = staff(conn, app, clock)
    assert ops.post("/api/regulatory", json={**BODY, **change}).status_code == 422
    assert conn.execute("SELECT count(*) FROM regulatory_config").fetchone()[0] == 0

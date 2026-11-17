from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from algo.core.clock import SimClock
from algo.data.store.migrate import migrate
from algo.research import holdout_cutoff
from tests.support.portal import add_user, enrol_second_factor, make_app, settings, sign_in
from tests.support.research_lock import anchor_open_lock

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


@pytest.fixture
def env(conn, pg_url, tmp_path):
    migrate(conn)
    anchor_open_lock(conn)
    clock = SimClock(START)
    return conn, make_app(pg_url, tmp_path, portal=settings(clock)), clock


def owner(conn, app, clock):
    add_user(conn, clock, "ADMIN", "boss@example.com")
    c = sign_in(app, "boss@example.com")
    enrol_second_factor(c, clock)
    return c


def test_only_the_owner_sees_the_holdout_ledger(env):
    conn, app, clock = env
    add_user(conn, clock, "TRADER", "jane@example.com")
    jane = sign_in(app, "jane@example.com")
    for method, path in (("GET", "/api/holdout"), ("POST", "/api/holdout/cutoffs/1/freeze")):
        assert (
            jane.request(
                method, path, json={"confirm": True} if method == "POST" else None
            ).status_code
            == 403
        ), path
        assert (
            TestClient(app)
            .request(method, path, json={"confirm": True} if method == "POST" else None)
            .status_code
            == 401
        ), path


def test_the_owner_sees_the_budget_the_batches_and_the_two_warnings_but_no_verdicts(env):
    conn, app, clock = env
    c = owner(conn, app, clock)
    d = c.get("/api/holdout").json()
    assert (d["budget"], d["consumed"], d["reserved"], d["left"], d["previously_tested"]) == (
        30,
        0,
        0,
        30,
        0,
    )
    assert d["batches"] == [] and d["cutoff"] is None and d["audit_signed"] is False
    assert (
        len(d["warnings"]) == 2
        and "not an untouched holdout" in d["warnings"][0]
        and "not proven here" in d["warnings"][1]
    )
    assert not any(k in d for k in ("verdicts", "p_value", "sharpe"))


def test_a_freeze_needs_a_confirmation_and_a_plan_that_allows_it(env):
    conn, app, clock = env
    c = owner(conn, app, clock)
    assert c.post("/api/holdout/cutoffs/1/freeze", json={}).status_code == 422
    assert c.post("/api/holdout/cutoffs/1/freeze", json={"confirm": False}).status_code == 422
    assert (
        c.post("/api/holdout/cutoffs/99/freeze", json={"confirm": True}).status_code == 404
    )  # no such cutoff
    cid = conn.execute(
        "INSERT INTO holdout_cutoff (kind, fired_at, snapshot, snapshot_sha256) VALUES ('BATCH1', %s, '{\"candidates\": []}', %s) RETURNING cutoff_id",
        (START, "0" * 64),
    ).fetchone()[0]
    r = c.post(f"/api/holdout/cutoffs/{cid}/freeze", json={"confirm": True})
    assert r.status_code == 409 and "not signed" in r.json()["detail"]
    shown = c.get("/api/holdout").json()["cutoff"]
    assert (
        shown["cutoff_id"] == cid
        and shown["plan"]["can_freeze"] is False
        and shown["plan"]["members"] == []
    )


def test_a_confirmed_freeze_is_audited(env, monkeypatch):
    conn, app, clock = env
    c = owner(conn, app, clock)
    monkeypatch.setattr(holdout_cutoff, "freeze_batch", lambda conn_, cid, by, now: 7)
    assert c.post("/api/holdout/cutoffs/5/freeze", json={"confirm": True}).json() == {
        "ok": True,
        "batch_id": 7,
    }
    assert (
        conn.execute(
            "SELECT count(*) FROM portal_audit WHERE action='holdout.batch_frozen'"
        ).fetchone()[0]
        == 1
    )

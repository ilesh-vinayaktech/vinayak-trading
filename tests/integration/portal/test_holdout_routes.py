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
    for method, path in (
        ("GET", "/api/holdout"),
        ("POST", "/api/holdout/cutoffs/1/freeze"),
        ("POST", "/api/holdout/submit"),
    ):
        assert (
            jane.request(
                method,
                path,
                json={"confirm": True, "candidates": ["A@1"]} if method == "POST" else None,
            ).status_code
            == 403
        ), path
        assert (
            TestClient(app)
            .request(
                method,
                path,
                json={"confirm": True, "candidates": ["A@1"]} if method == "POST" else None,
            )
            .status_code
            == 401
        ), path


def test_the_owner_sees_the_budget_the_batches_and_the_two_warnings_(env):
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
    assert d["results"] == [] and not any(k in d for k in ("p_value", "sharpe"))


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


def test_submit_needs_a_confirmation_a_declaration_and_is_audited(env, monkeypatch):
    conn, app, clock = env
    c = owner(conn, app, clock)
    assert c.post("/api/holdout/submit", json={"candidates": ["A@1"]}).status_code == 422
    assert (
        c.post("/api/holdout/submit", json={"candidates": [], "confirm": True}).status_code == 422
    )
    r = c.post(
        "/api/holdout/submit", json={"candidates": ["A@1"], "declaration": " ", "confirm": True}
    )
    assert r.status_code == 409 and "not built from 2025-2026" in r.json()["detail"]
    monkeypatch.setattr(holdout_cutoff, "submit", lambda conn_, ids, text, by, now: 9)
    body = {"candidates": ["A@1", "B@1"], "declaration": "from 2016-2022 only", "confirm": True}
    assert c.post("/api/holdout/submit", json=body).json() == {"ok": True, "batch_id": 9}
    assert (
        conn.execute(
            "SELECT count(*) FROM portal_audit WHERE action='holdout.batch_submitted'"
        ).fetchone()[0]
        == 1
    )


def test_the_page_lists_what_can_be_submitted_with_its_inner_holdout_outcome(env, monkeypatch):
    conn, app, clock = env
    c = owner(conn, app, clock)
    assert c.get("/api/holdout").json()["eligible"] == []
    cand = lambda cid, verdict, slot=None, why=None: {  # noqa: E731
        "candidate_id": cid,
        "experiment_id": 999,
        "development_verdict": verdict,
        "slot": slot,
        "excluded_reason": why,
    }
    monkeypatch.setattr(
        holdout_cutoff,
        "snapshot",
        lambda conn_: {"candidates": [cand("OK@1", "PASSED"), cand("F@1", "FAILED"), cand("U@1", "PASSED", slot="CONSUMED"), cand("X@1", "PASSED", why=3), cand("D@1", "PASSED")]},
    )  # fmt: skip
    monkeypatch.setattr(
        holdout_cutoff, "_clean_passed_study", lambda conn_, sid, ver: None if sid == "D" else 1
    )
    assert c.get("/api/holdout").json()["eligible"] == [{"candidate_id": "OK@1", "inner": None}]


def test_results_show_each_check_with_later_completions_marked_and_never_a_figure(env, monkeypatch):
    conn, app, clock = env
    c = owner(conn, app, clock)
    from algo.promotion import verdicts as pv

    rows = [
        ("study-3", "holdout_sharpe", "FAIL"), ("study-3", "holdout_drawdown", "INSUFFICIENT_EVIDENCE"),
        ("study-17", "holdout_sharpe", "PASS"), ("study-17", "holdout_drawdown", "INSUFFICIENT_EVIDENCE"),
        ("study-18", "holdout_sharpe", "PASS"), ("study-18", "holdout_drawdown", "INSUFFICIENT_EVIDENCE"),
    ]  # fmt: skip
    monkeypatch.setattr(pv, "read_verdicts", lambda conn_: rows)
    monkeypatch.setattr(
        pv,
        "read_supplements",
        lambda conn_: [
            ("study-17", "holdout_drawdown", "PASS"),
            ("study-3", "holdout_drawdown", "PASS"),
        ],
    )
    got = {r["name"]: r for r in c.get("/api/holdout").json()["results"]}
    assert got["study-17"]["overall"] == "PASS" and got["study-3"]["overall"] == "FAIL"
    assert (
        got["study-18"]["overall"] == "INCOMPLETE"
    )  # a check still without evidence is never a pass
    assert {"gate": "holdout_drawdown", "verdict": "PASS", "later": True} in got["study-17"][
        "checks"
    ]
    assert {"gate": "holdout_sharpe", "verdict": "PASS", "later": False} in got["study-17"][
        "checks"
    ]

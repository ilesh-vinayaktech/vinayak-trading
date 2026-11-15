# ruff: noqa: E501
"""The read-only research-intelligence API: every number comes from rows the Phase 1 to 5 parts wrote."""

import random
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from algo.alpha import registry as alpha_registry
from algo.alpha.discover import Evidence
from algo.data.store.migrate import migrate
from algo.features import store as feature_store
from algo.learning import memory
from algo.portfolio import audit
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def series(seed, vol, n=60):
    rng = random.Random(seed)
    return [rng.gauss(0.0005, vol) for _ in range(n)]


@pytest.fixture
def client(conn, pg_url, tmp_path):
    migrate(conn)
    conn.commit()
    return TestClient(open_app(pg_url, tmp_path)), conn


def test_an_empty_database_gives_an_honest_empty_overview(client):
    c, _ = client
    body = c.get("/api/intel/overview").json()
    assert body["features"] == {"by_status": {}} and body["alpha"] == {
        "tests_ever_run": 0,
        "by_status": {},
    }
    assert body["factory"] == {"definitions": 0, "experiments": 0, "trials": 0} and body[
        "notes"
    ] == {"total": 0}
    assert body["health"] == [] and body["allocation"] is None
    assert c.get("/api/intel/alpha").json() == {"hypotheses": []}
    assert c.get("/api/intel/notes").json() == {"notes": []}
    assert c.get("/api/intel/allocations").json() == {"allocations": []}


def test_the_overview_and_lists_show_what_the_parts_recorded(client):
    c, conn = client
    feature_store.register_all(conn, NOW)
    good = Evidence("ret_5d", "1", 5, 500, 150.0, 0.05, 0.1, 0.5, 0.6, 4.0, 0.0001)
    bad = Evidence("ret_20d", "1", 20, 500, 150.0, 0.0, 0.1, 0.0, 0.5, 0.0, 0.9)
    alpha_registry.record(conn, [good, bad], "d" * 64, NOW)
    memory.add(conn, "DECISION", "capital", "Paper capital Rs 1 lakh", by="owner", now=NOW)
    memory.sync_alpha(conn, now=NOW)
    r = {"A": series(1, 0.01), "B": series(2, 0.02), "C": series(3, 0.015), "D": series(4, 0.01)}
    audit.recommend_and_record(
        conn, r, dict.fromkeys(r, "OK"), by="jane", now=NOW, method="EQUAL_RISK"
    )
    conn.execute(
        "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,'degradation','paper u1 vs backtest run 1',NULL,'FAIL','DEGRADED: mean return -0.5%% a day')",
        (NOW,),
    )
    conn.commit()

    o = c.get("/api/intel/overview").json()
    assert o["features"]["by_status"] == {"DRAFT": 12}
    assert o["alpha"] == {"tests_ever_run": 2, "by_status": {"CANDIDATE": 1, "REJECTED": 1}}
    assert o["notes"] == {"total": 3}
    assert o["health"][0]["status"] == "FAIL" and o["health"][0]["detail"].startswith("DEGRADED")
    assert (
        o["allocation"]["method"] == "EQUAL_RISK"
        and o["allocation"]["by"] == "jane"
        and sum(o["allocation"]["weights"].values()) <= 1.0
    )

    hyp = c.get("/api/intel/alpha").json()["hypotheses"]
    assert [(h["feature"], h["status"], h["direction"]) for h in hyp] == [
        ("ret_20d", "REJECTED", None),
        ("ret_5d", "CANDIDATE", "POSITIVE"),
    ]
    only = c.get("/api/intel/alpha", params={"status": "CANDIDATE"}).json()["hypotheses"]
    assert (
        [h["feature"] for h in only] == ["ret_5d"]
        and only[0]["mean_ic"] == 0.05
        and only[0]["horizon"] == 5
    )

    assert [n["kind"] for n in c.get("/api/intel/notes").json()["notes"]] == [
        "FAILURE",
        "FINDING",
        "DECISION",
    ]  # newest first
    assert [
        n["subject"] for n in c.get("/api/intel/notes", params={"q": "capital"}).json()["notes"]
    ] == ["capital"]
    assert [
        n["kind"] for n in c.get("/api/intel/notes", params={"kind": "FAILURE"}).json()["notes"]
    ] == ["FAILURE"]
    al = c.get("/api/intel/allocations").json()["allocations"]
    assert len(al) == 1 and al[0]["risk_contribution"] and al[0]["notes"] is not None


def test_bad_filters_are_refused_and_nothing_can_be_written_through_this_api(client):
    c, conn = client
    assert c.get("/api/intel/alpha", params={"status": "MAYBE"}).status_code == 422
    assert c.get("/api/intel/notes", params={"kind": "OPINION"}).status_code == 422
    assert c.get("/api/intel/alpha", params={"limit": 0}).status_code == 422
    for path in ("overview", "alpha", "notes", "allocations"):
        assert c.post(f"/api/intel/{path}", json={}).status_code == 405
        assert c.delete(f"/api/intel/{path}").status_code == 405
    assert conn.execute("SELECT count(*) FROM research_note").fetchone() == (0,)

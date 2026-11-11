import json
from datetime import UTC, date, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

from algo.api import reviews
from algo.data.store.migrate import migrate
from tests.support.portal import open_app

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 8, tzinfo=UTC)
ITEM = {
    "id": "symbol:X", "kind": "SYMBOL_IDENTITY", "title": "X", "question": "q", "context": {}, "leads": [],
    "options": [
        {"value": "MAP", "label": "map", "needs_date": True},
        {"value": "SPAN", "label": "span", "needs_date": True, "has_end": True},
        {"value": "SEP", "label": "separate", "needs_date": False},
        {"value": "NEEDS_MORE_EVIDENCE", "label": "more", "needs_date": False, "needs_evidence": False},
    ],
}  # fmt: skip


def d(**kw):
    return reviews.DecisionIn(**{"reviewer": "ilesh", "evidence_ref": "pr_ind_prs1", **kw})


@pytest.fixture
def conn_m(conn):
    migrate(conn)
    return conn


def test_listing_shows_latest_decision_and_history_keeps_all(conn_m):
    reviews.record(conn_m, ITEM, d(decision="SEP"), NOW)
    reviews.record(
        conn_m, ITEM, d(decision="MAP", effective_date=date(2022, 4, 1), note=" n "), NOW
    )
    out = reviews.listing(conn_m, [ITEM, {**ITEM, "id": "symbol:Y"}])
    assert out["total"] == 2 and out["decided"] == 1
    assert (
        out["items"][0]["latest"]["decision"] == "MAP" and out["items"][0]["latest"]["note"] == "n"
    )
    assert out["items"][1]["latest"] is None
    assert [h["decision"] for h in reviews.history(conn_m, "symbol:X")] == ["MAP", "SEP"]


def test_needs_more_evidence_does_not_count_as_decided(conn_m):
    reviews.record(conn_m, ITEM, d(decision="NEEDS_MORE_EVIDENCE", evidence_ref=""), NOW)
    assert reviews.listing(conn_m, [ITEM])["decided"] == 0


@pytest.mark.parametrize(
    ("body", "msg"),
    [
        (dict(decision="NOPE"), "not an option"),
        (dict(decision="MAP"), "needs an effective date"),
        (dict(decision="SEP", effective_date=date(2022, 1, 1)), "takes no date"),
        (
            dict(decision="MAP", effective_date=date(2022, 1, 1), effective_to=date(2023, 1, 1)),
            "no end date",
        ),
        (
            dict(decision="SPAN", effective_date=date(2023, 1, 1), effective_to=date(2022, 1, 1)),
            "before the start",
        ),
        (dict(decision="SEP", evidence_ref="  "), "cite the source"),
    ],
)
def test_invalid_decisions_are_refused_and_nothing_is_written(conn_m, body, msg):
    with pytest.raises(reviews.ReviewError, match=msg):
        reviews.record(conn_m, ITEM, d(**body), NOW)
    assert conn_m.execute("SELECT count(*) FROM review_decision").fetchone()[0] == 0


def test_decisions_are_append_only(conn_m):
    reviews.record(conn_m, ITEM, d(decision="SEP"), NOW)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn_m.execute("UPDATE review_decision SET note='x'")


def test_missing_items_file_is_an_empty_queue(tmp_path):
    assert reviews.load_items(tmp_path / "none.json") == []


@pytest.fixture
def client(conn_m, tmp_path, pg_url):
    f = tmp_path / "items.json"
    f.write_text(json.dumps({"items": [ITEM]}))

    def make(writes):
        return TestClient(open_app(pg_url, tmp_path, reviews_file=f, review_writes=writes))

    return make


def test_api_lists_posts_and_reads_history(client):
    c = client(True)
    assert c.get("/api/reviews").json()["writes_enabled"] is True
    r = c.post(
        "/api/reviews/symbol:X/decisions",
        json={
            "decision": "MAP",
            "reviewer": "ilesh",
            "evidence_ref": "doc",
            "effective_date": "2022-04-01",
        },
    )
    assert r.status_code == 201
    got = c.get("/api/reviews").json()
    assert got["decided"] == 1 and got["items"][0]["latest"]["effective_date"] == "2022-04-01"
    assert len(c.get("/api/reviews/symbol:X/history").json()) == 1


def test_api_refuses_bad_input_unknown_item_foreign_origin_and_disabled_writes(client):
    c = client(True)
    ok = {"decision": "SEP", "reviewer": "ilesh", "evidence_ref": "doc"}
    assert (
        c.post("/api/reviews/symbol:X/decisions", json={**ok, "decision": "NOPE"}).status_code
        == 422
    )
    assert c.post("/api/reviews/symbol:X/decisions", json={**ok, "extra": 1}).status_code == 422
    assert c.post("/api/reviews/symbol:ZZ/decisions", json=ok).status_code == 404
    assert (
        c.post(
            "/api/reviews/symbol:X/decisions", json=ok, headers={"Origin": "http://evil.example"}
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/reviews/symbol:X/decisions", json=ok, headers={"Origin": "http://localhost:3000"}
        ).status_code
        == 201
    )
    assert client(False).post("/api/reviews/symbol:X/decisions", json=ok).status_code == 403

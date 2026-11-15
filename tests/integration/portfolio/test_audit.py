# ruff: noqa: E501
import random
from datetime import UTC, datetime

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.portfolio import allocation, audit

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def series(seed, vol, n=60):
    rng = random.Random(seed)
    return [rng.gauss(0.0005, vol) for _ in range(n)]


R = {"A": series(1, 0.01), "B": series(2, 0.02), "C": series(3, 0.015), "D": series(4, 0.01)}
H = dict.fromkeys(R, "OK")


def test_a_recommendation_is_stored_with_its_inputs_and_matches_what_was_returned(conn):
    migrate(conn)
    rid, res = audit.recommend_and_record(
        conn, R, H, by="jane", now=NOW, method="EQUAL_RISK", target_vol=0.02
    )
    row = conn.execute(
        "SELECT method, limits, target_vol, health, inputs_sha256, weights, cash, created_by FROM allocation_recommendation WHERE recommendation_id=%s",
        (rid,),
    ).fetchone()
    assert (
        row[0] == "EQUAL_RISK"
        and row[1] == {"max_single": 0.35, "max_total": 1.0}
        and row[2] == 0.02
        and row[3] == H
    )
    assert (
        row[4] == audit.inputs_hash(R, H)
        and row[5] == res.weights
        and row[6] == pytest.approx(res.cash)
        and row[7] == "jane"
    )


def test_the_inputs_hash_changes_when_any_return_or_health_changes_and_not_with_key_order():
    base = audit.inputs_hash(R, H)
    assert (
        audit.inputs_hash(dict(reversed(list(R.items()))), dict(reversed(list(H.items())))) == base
    )
    tweaked = {**R, "A": [*R["A"][:-1], R["A"][-1] + 1e-9]}
    assert (
        audit.inputs_hash(tweaked, H) != base and audit.inputs_hash(R, {**H, "B": "WATCH"}) != base
    )


def test_changes_since_the_last_recommendation_are_reported(conn):
    migrate(conn)
    first, _ = audit.recommend_and_record(conn, R, H, by="jane", now=NOW, method="EQUAL_RISK")
    assert audit.changes_since_last(conn, first) == {}  # nothing before it
    second, _ = audit.recommend_and_record(
        conn, R, {**H, "B": "DEGRADED"}, by="jane", now=NOW, method="EQUAL_RISK"
    )
    diff = audit.changes_since_last(conn, second)
    assert diff["B"][1] == 0.0 and diff["B"][0] > 0 and set(diff) == {"A", "B", "C", "D"}
    third, _ = audit.recommend_and_record(
        conn, R, {**H, "B": "DEGRADED"}, by="jane", now=NOW, method="EQUAL_RISK"
    )
    assert audit.changes_since_last(conn, third) == {}  # same advice again: no change
    assert audit.changes_since_last(conn, first) == {}  # the first one still has nothing before it


def test_advice_is_never_changed_or_removed_and_a_bad_request_stores_nothing(conn):
    migrate(conn)
    audit.recommend_and_record(conn, R, H, by="jane", now=NOW)
    for sql in (
        "UPDATE allocation_recommendation SET cash=0",
        "DELETE FROM allocation_recommendation",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
            conn.execute(sql)
    with pytest.raises(allocation.AllocationError, match="who asked"):
        audit.recommend_and_record(conn, R, H, by=" ", now=NOW)
    with pytest.raises(allocation.AllocationError):
        audit.recommend_and_record(conn, R, H, by="jane", now=NOW, method="MAGIC")
    assert conn.execute("SELECT count(*) FROM allocation_recommendation").fetchone() == (1,)

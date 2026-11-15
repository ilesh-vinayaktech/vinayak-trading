# ruff: noqa: E501
from datetime import UTC, datetime

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.factory import dsl, registry

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
BASE = {
    "strategy_id": "MOM_001", "version": 1, "description": "momentum", "universe": "MEMBERS", "timeframe": "DAILY",
    "entry": {"all": [{"feature": "ret_60d", "op": ">", "value": 0.05}]},
    "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": 0}]},
    "ranking": {"feature": "ret_60d", "order": "DESC"},
    "position": {"max_positions": 10, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 10},
}  # fmt: skip


def make(**over):
    return dsl.StrategyDef.model_validate({**BASE, **over})


def test_a_first_version_is_stored_with_who_why_and_its_hash_and_read_back_as_the_same_definition(
    conn,
):
    migrate(conn)
    d = make()
    registry.register(conn, d, by="jane", reason="first idea", now=NOW)
    back = registry.get(conn, "MOM_001", 1)
    assert back == d and back.sha256 == d.sha256
    assert conn.execute(
        "SELECT parent_version, reason, created_by, definition_sha256 FROM strategy_definition"
    ).fetchone() == (None, "first idea", "jane", d.sha256)


def test_every_change_is_a_new_version_that_points_at_the_one_before_and_says_why(conn):
    migrate(conn)
    registry.register(conn, make(), by="jane", reason="first idea", now=NOW)
    v2 = make(version=2, risk={"max_position_percent": 8})
    registry.register(
        conn, v2, by="jane", reason="smaller positions after the drawdown review", now=NOW
    )
    assert conn.execute(
        "SELECT version, parent_version FROM strategy_definition ORDER BY version"
    ).fetchall() == [(1, None), (2, 1)]
    assert registry.versions(conn, "MOM_001") == [1, 2] and registry.latest(conn, "MOM_001") == v2
    assert (
        registry.get(conn, "MOM_001", 1).risk.max_position_percent != v2.risk.max_position_percent
    )  # version 1 is untouched


def test_versions_must_follow_one_another_and_a_new_version_must_actually_change_a_rule(conn):
    migrate(conn)
    registry.register(conn, make(), by="jane", reason="first", now=NOW)
    with pytest.raises(registry.RegistryError, match="next version"):
        registry.register(conn, make(version=3), by="jane", reason="skipped one", now=NOW)
    with pytest.raises(registry.RegistryError, match="next version"):
        registry.register(conn, make(version=1), by="jane", reason="overwrite", now=NOW)
    with pytest.raises(registry.RegistryError, match="no rule differs"):
        registry.register(
            conn,
            make(version=2, description="a reworded description"),
            by="jane",
            reason="same rules",
            now=NOW,
        )
    with pytest.raises(registry.RegistryError, match="first version must be 1"):
        registry.register(
            conn,
            make(strategy_id="OTHER_001", version=2),
            by="jane",
            reason="starts at two",
            now=NOW,
        )
    assert registry.versions(conn, "MOM_001") == [1]


def test_a_reason_and_an_author_are_required(conn):
    migrate(conn)
    for by, reason in (("", "x"), ("jane", ""), ("  ", "x"), ("jane", "   ")):
        with pytest.raises(registry.RegistryError, match="who and why"):
            registry.register(conn, make(), by=by, reason=reason, now=NOW)
    assert registry.versions(conn, "MOM_001") == []


def test_a_stored_version_is_never_changed_or_removed(conn):
    migrate(conn)
    registry.register(conn, make(), by="jane", reason="first", now=NOW)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE strategy_definition SET reason='edited'")
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("DELETE FROM strategy_definition")


def test_a_row_whose_content_no_longer_matches_its_hash_is_refused_when_read(conn):
    migrate(conn)
    registry.register(conn, make(), by="jane", reason="first", now=NOW)
    conn.execute(
        "ALTER TABLE strategy_definition DISABLE TRIGGER strategy_definition_insert_only"
    )  # what a tamperer with database access would have to do first
    conn.execute(
        "UPDATE strategy_definition SET definition = jsonb_set(definition, '{position,max_positions}', '40')"
    )
    with pytest.raises(registry.RegistryError, match="does not match its hash"):
        registry.get(conn, "MOM_001", 1)


def test_unknown_strategies_and_versions_are_reported_as_such(conn):
    migrate(conn)
    registry.register(conn, make(), by="jane", reason="first", now=NOW)
    with pytest.raises(registry.RegistryError, match="no version 2"):
        registry.get(conn, "MOM_001", 2)
    with pytest.raises(registry.RegistryError, match="no strategy"):
        registry.latest(conn, "NOPE_001")
    assert registry.versions(conn, "NOPE_001") == []

# ruff: noqa: E501
"""The strategy definition registry (plan.md section 7.3): every version of every definition is an immutable row; a change is a new version.

Callers: tests/integration/factory/test_registry.py and the factory scripts. Schema: strategy_definition (migration 079, insert-only).
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".

  * Versions are 1, 2, 3 ... with no gaps and no overwrites; each names the version before it and a reason, and the person who made it.
  * A new version must change a RULE (anything but the version number and the description); a reworded description is not a new strategy.
  * What is read back is checked against the hash stored with it, so a row altered behind the database's back is refused, not run.
  * This registry holds no status and promotes nothing: whether a version may go to paper or live is decided by the existing validation and lifecycle gates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.factory.dsl import StrategyDef


class RegistryError(Exception):
    pass


def _rules(defn: StrategyDef) -> dict[str, Any]:
    c = defn.canonical()
    c.pop("version")
    c.pop("description")
    return c


def versions(conn: psycopg.Connection, strategy_id: str) -> list[int]:
    return [
        int(r[0])
        for r in conn.execute(
            "SELECT version FROM strategy_definition WHERE strategy_id=%s ORDER BY version",
            (strategy_id,),
        )
    ]


def get(conn: psycopg.Connection, strategy_id: str, version: int) -> StrategyDef:
    row = conn.execute(
        "SELECT definition, definition_sha256 FROM strategy_definition WHERE strategy_id=%s AND version=%s",
        (strategy_id, version),
    ).fetchone()
    if row is None:
        raise RegistryError(f"no version {version} of {strategy_id}")
    defn = StrategyDef.model_validate(row[0])
    if defn.sha256 != row[1]:
        raise RegistryError(
            f"{strategy_id} version {version} does not match its hash: the stored row was altered"
        )
    return defn


def latest(conn: psycopg.Connection, strategy_id: str) -> StrategyDef:
    have = versions(conn, strategy_id)
    if not have:
        raise RegistryError(f"no strategy {strategy_id}")
    return get(conn, strategy_id, have[-1])


def register(
    conn: psycopg.Connection, defn: StrategyDef, *, by: str, reason: str, now: datetime
) -> int:
    """Store `defn` as the next version of its strategy. Returns the row id."""
    if not by.strip() or not reason.strip():
        raise RegistryError("a new version needs who and why")
    now = require_utc(now)
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (defn.strategy_id,)
        )  # two writers cannot both take the same next version
        have = versions(conn, defn.strategy_id)
        expected = have[-1] + 1 if have else 1
        if defn.version != expected:
            if not have:
                raise RegistryError(f"the first version must be 1, not {defn.version}")
            raise RegistryError(
                f"the next version of {defn.strategy_id} is {expected}, not {defn.version}"
            )
        if have and _rules(get(conn, defn.strategy_id, have[-1])) == _rules(defn):
            raise RegistryError(
                f"no rule differs from version {have[-1]}: change a rule, or do not make a new version"
            )
        row = conn.execute(
            "INSERT INTO strategy_definition (strategy_id, version, parent_version, reason, definition, definition_sha256, created_by, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING definition_id",
            (
                defn.strategy_id,
                defn.version,
                have[-1] if have else None,
                reason.strip(),
                Jsonb(defn.canonical()),
                defn.sha256,
                by.strip(),
                now,
            ),
        ).fetchone()
        assert row is not None
        return int(row[0])

# ruff: noqa: E501
"""Saved, named strategy settings per user (strategy_config, migration 040).

A paper account runs the settings copied onto it (paper_account.universe / max_instruments / timeframe / params), so the
runner is untouched. `use` copies a config onto the caller's account and remembers which; `update` rewrites the config and
every account using it, so editing a config is how its settings change everywhere. A config belongs to one user: another
person's id looks like it does not exist."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.paper.book import PaperError, _check_settings

COLUMNS = "config_id, name, strategy_id, universe, max_instruments, timeframe, params, created_at, EXISTS (SELECT 1 FROM paper_account a WHERE a.config_id = c.config_id) AS in_use"
KEYS = [
    "config_id", "name", "strategy_id", "universe", "max_instruments", "timeframe", "params", "created_at", "in_use",
]  # fmt: skip


class ConfigError(ValueError):
    pass


def _check(name: str, universe: str, max_instruments: int | None, timeframe: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise ConfigError("the name must be 1 to 60 characters")
    try:
        _check_settings(universe, max_instruments, timeframe)
    except PaperError as e:
        raise ConfigError(str(e)) from e
    return name


def _taken() -> ConfigError:
    return ConfigError("you already have a strategy with that name")


def get(conn: psycopg.Connection, owner: UUID, config_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {COLUMNS} FROM strategy_config c WHERE owner_user_id=%s AND config_id=%s",
        (owner, config_id),
    ).fetchone()
    return None if row is None else dict(zip(KEYS, row, strict=True))


def _need(conn: psycopg.Connection, owner: UUID, config_id: UUID) -> dict[str, Any]:
    found = get(conn, owner, config_id)
    if found is None:
        raise ConfigError("no such strategy")
    return found


def list_for(conn: psycopg.Connection, owner: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM strategy_config c WHERE owner_user_id=%s ORDER BY created_at, name",
        (owner,),
    ).fetchall()
    return [dict(zip(KEYS, r, strict=True)) for r in rows]


def create(
    conn: psycopg.Connection,
    owner: UUID,
    *,
    name: str,
    universe: str,
    max_instruments: int | None,
    timeframe: str,
    params: dict[str, Any],
    now: datetime,
    strategy_id: str = "trend_pullback",
) -> UUID:
    name = _check(name, universe, max_instruments, timeframe)
    try:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO strategy_config (owner_user_id, name, strategy_id, universe, max_instruments, timeframe, params, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING config_id",
                (
                    owner,
                    name,
                    strategy_id,
                    universe,
                    max_instruments,
                    timeframe,
                    Jsonb(params),
                    now,
                ),
            ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise _taken() from e
    assert row is not None
    config_id: UUID = row[0]
    return config_id


def update(
    conn: psycopg.Connection,
    owner: UUID,
    config_id: UUID,
    *,
    name: str,
    universe: str,
    max_instruments: int | None,
    timeframe: str,
    params: dict[str, Any],
) -> None:
    _need(conn, owner, config_id)
    name = _check(name, universe, max_instruments, timeframe)
    try:
        with conn.transaction():
            conn.execute(
                "UPDATE strategy_config SET name=%s, universe=%s, max_instruments=%s, timeframe=%s, params=%s WHERE config_id=%s",
                (name, universe, max_instruments, timeframe, Jsonb(params), config_id),
            )
            conn.execute(
                "UPDATE paper_account SET universe=%s, max_instruments=%s, timeframe=%s, params=%s WHERE config_id=%s",
                (universe, max_instruments, timeframe, Jsonb(params), config_id),
            )
    except psycopg.errors.UniqueViolation as e:
        raise _taken() from e


def use(conn: psycopg.Connection, owner: UUID, config_id: UUID) -> None:
    c = _need(conn, owner, config_id)
    done = conn.execute(
        "UPDATE paper_account SET universe=%s, max_instruments=%s, timeframe=%s, params=%s, config_id=%s WHERE user_id=%s",
        (c["universe"], c["max_instruments"], c["timeframe"], Jsonb(c["params"]), config_id, owner),
    )
    if done.rowcount == 0:
        raise ConfigError("no paper account yet")


def delete(conn: psycopg.Connection, owner: UUID, config_id: UUID) -> None:
    if _need(conn, owner, config_id)["in_use"]:
        raise ConfigError("this strategy is in use by your paper account; pick another first")
    conn.execute("DELETE FROM strategy_config WHERE config_id=%s", (config_id,))

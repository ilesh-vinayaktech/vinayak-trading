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

from algo.paper import book
from algo.paper.book import PaperError, _check_settings
from algo.strategy import stage

COLUMNS = "config_id, name, strategy_id, universe, max_instruments, timeframe, params, screen, created_at, EXISTS (SELECT 1 FROM paper_account a WHERE a.config_id = c.config_id) AS in_use"
KEYS = [
    "config_id", "name", "strategy_id", "universe", "max_instruments", "timeframe", "params", "screen", "created_at", "in_use",
]  # fmt: skip


SEGMENTS = (
    "segments"  # the universe of a screener strategy: its market-cap classes live in `screen`
)


class ConfigError(ValueError):
    pass


def _check(name: str, universe: str, max_instruments: int | None, timeframe: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise ConfigError("the name must be 1 to 60 characters")
    try:
        _check_settings("nifty50" if universe == SEGMENTS else universe, max_instruments, timeframe)
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
    screen: dict[str, Any] | None = None,
) -> UUID:
    name = _check(name, universe, max_instruments, timeframe)
    try:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO strategy_config (owner_user_id, name, strategy_id, universe, max_instruments, timeframe, params, screen, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING config_id",
                (
                    owner,
                    name,
                    strategy_id,
                    universe,
                    max_instruments,
                    timeframe,
                    Jsonb(params),
                    None if screen is None else Jsonb(screen),
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
    screen: dict[str, Any] | None = None,
) -> None:
    if (_need(conn, owner, config_id)["screen"] is None) != (screen is None):
        raise ConfigError("a screener strategy stays a screener, and any other stays what it is")
    name = _check(name, universe, max_instruments, timeframe)
    try:
        with conn.transaction():
            conn.execute(
                "UPDATE strategy_config SET name=%s, universe=%s, max_instruments=%s, timeframe=%s, params=%s, screen=%s WHERE config_id=%s",
                (
                    name,
                    universe,
                    max_instruments,
                    timeframe,
                    Jsonb(params),
                    None if screen is None else Jsonb(screen),
                    config_id,
                ),
            )
            conn.execute(
                "UPDATE paper_account SET universe=%s, max_instruments=%s, timeframe=%s, params=%s, screen=%s WHERE config_id=%s",
                (
                    universe,
                    max_instruments,
                    timeframe,
                    Jsonb(params),
                    None if screen is None else Jsonb(screen),
                    config_id,
                ),
            )
    except psycopg.errors.UniqueViolation as e:
        raise _taken() from e


def use(conn: psycopg.Connection, owner: UUID, config_id: UUID, mode: str = "PAPER") -> None:
    """Give this person's paper (or live) account the strategy. A LIVE account runs only a strategy in the LIVE stage."""
    c = _need(conn, owner, config_id)
    if mode == "LIVE" and stage.current(conn, config_id) != "LIVE":
        raise ConfigError("a live account runs only a strategy promoted to the LIVE stage")
    done = conn.execute(
        "UPDATE paper_account SET strategy_id=%s, universe=%s, max_instruments=%s, timeframe=%s, params=%s, screen=%s, definition=NULL, config_id=%s WHERE user_id=%s",
        (
            c["strategy_id"],
            c["universe"],
            c["max_instruments"],
            c["timeframe"],
            Jsonb(c["params"]),
            None if c["screen"] is None else Jsonb(c["screen"]),
            config_id,
            book.account_key(owner, mode),
        ),
    )
    if done.rowcount == 0:
        raise ConfigError(f"no {mode.lower()} account yet")


def delete(conn: psycopg.Connection, owner: UUID, config_id: UUID) -> None:
    if _need(conn, owner, config_id)["in_use"]:
        raise ConfigError("this strategy is in use by your paper account; pick another first")
    conn.execute("DELETE FROM strategy_config WHERE config_id=%s", (config_id,))

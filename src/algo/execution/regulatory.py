# ruff: noqa: E501
"""The regulatory configuration (spec section 11, P1): what the exchange and Kite require of an algo order, with the day a person last
verified each item. Live trading is blocked when a required item is missing or was last verified too long ago, because a rule that
changed under us (order-rate cap, market protection, tagging, static IP) is exactly how a live order gets refused or flagged.
Nothing is assumed: an empty table means live is blocked until the owner records what they have read."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

EXCHANGE, SEGMENT = "NSE", "CM"  # the cash segment: all this platform trades
REQUIRED = ("ops_limit", "order_types", "tagging", "static_ip")
MAX_AGE = timedelta(days=30)


@dataclass(frozen=True)
class Item:
    exchange: str
    segment: str
    topic: str
    value: Any
    effective_from: date
    source: str
    last_verified: date
    verified_by: str


def problems(
    items: Iterable[Item],
    today: date,
    *,
    required: Iterable[str] = REQUIRED,
    max_age: timedelta = MAX_AGE,
    exchange: str = EXCHANGE,
    segment: str = SEGMENT,
) -> list[str]:
    """Every reason live must stay blocked: a required topic with no row in force yet, or last verified more than `max_age` ago. `items` are the newest per topic."""
    have = {i.topic: i for i in items if (i.exchange, i.segment) == (exchange, segment)}
    out = []
    for topic in required:
        i = have.get(topic)
        if i is None or i.effective_from > today:
            out.append(f"regulatory: {topic} is not recorded for {exchange} {segment}")
        elif today - i.last_verified > max_age:
            out.append(
                f"regulatory: {topic} was last verified {i.last_verified} (more than {max_age.days} days ago)"
            )
    return out


def record(conn: psycopg.Connection, item: Item) -> None:
    """A new row: a first entry, a change, or a re-check (the same value with a newer `last_verified`)."""
    conn.execute(
        "INSERT INTO regulatory_config (exchange, segment, topic, value, effective_from, source, last_verified, verified_by)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            item.exchange,
            item.segment,
            item.topic,
            Jsonb(item.value),
            item.effective_from,
            item.source,
            item.last_verified,
            item.verified_by,
        ),
    )


def in_force(conn: psycopg.Connection) -> list[Item]:
    """The newest row per exchange, segment and topic."""
    rows = conn.execute(
        "SELECT DISTINCT ON (exchange, segment, topic) exchange, segment, topic, value, effective_from, source, last_verified, verified_by"
        " FROM regulatory_config ORDER BY exchange, segment, topic, id DESC"
    ).fetchall()
    return [Item(*r) for r in rows]


def check(conn: psycopg.Connection, today: date) -> list[str]:
    return problems(in_force(conn), today)

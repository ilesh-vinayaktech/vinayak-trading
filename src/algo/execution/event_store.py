# ruff: noqa: E501
"""Where the OMS keeps its order events. The OMS appends each event as it happens and replays everything on start, so an order
survives a restart. Values are stored with the sandbox protocol's tags so Decimals and datetimes come back exactly as written."""

from __future__ import annotations

import json
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

from algo.execution.orders import OrderEvent, State
from algo.sandbox.protocol import dumps, loads


class EventStore(Protocol):
    def append(self, ev: OrderEvent) -> None: ...
    def load(self) -> dict[str, list[OrderEvent]]: ...


class MemoryStore:
    """Nothing is kept: for tests and for runs that do not need to survive."""

    def append(self, ev: OrderEvent) -> None:
        return None

    def load(self) -> dict[str, list[OrderEvent]]:
        return {}


class DbStore:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def append(self, ev: OrderEvent) -> None:
        self.conn.execute(
            "INSERT INTO oms_event (order_id, seq, ts, state, kind, data) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                ev.order_id,
                ev.seq,
                ev.ts,
                ev.state.value if ev.state else None,
                ev.kind,
                Jsonb(json.loads(dumps(ev.data))),
            ),
        )

    def load(self) -> dict[str, list[OrderEvent]]:
        out: dict[str, list[OrderEvent]] = {}
        rows = self.conn.execute(
            "SELECT order_id, seq, ts, state, kind, data FROM oms_event ORDER BY order_id, seq"
        ).fetchall()
        for oid, seq, ts, state, kind, data in rows:
            decoded: dict[str, Any] = loads(json.dumps(data))
            out.setdefault(oid, []).append(
                OrderEvent(oid, seq, ts, State(state) if state else None, kind, decoded)
            )
        return out

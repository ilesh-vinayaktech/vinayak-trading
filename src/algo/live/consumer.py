# ruff: noqa: E501
"""A durable consumer of the live bars (docs: TODO 5.3). The feed writes `live_bar_1m` and announces each new bar on the Postgres
channel `live_bar`; a consumer asks "what was written after my offset?" and commits its offset in the SAME transaction as its own
work, so a crash neither loses a bar nor handles one twice (a handler that fails rolls both back and the bars come again: at least
once, and the handler must be idempotent). The order is the order the feed wrote the bars (built_at, instrument, minute), so a bar
that arrives late for an earlier minute is delivered, not skipped. The feed itself never repeats a bar (ON CONFLICT DO NOTHING), so
a duplicate from the exchange is delivered once.
Limit: the order is by write time, which assumes one feed writer committing in order (true today: one feed service)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg

CLOCK_TOLERANCE = timedelta(
    seconds=60
)  # a bar from the future by more than this means the clocks disagree


@dataclass(frozen=True)
class Delivered:
    instrument_id: int
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    partial: bool
    built_at: datetime


class BarConsumer:
    def __init__(self, conn: psycopg.Connection, name: str, *, start_after: datetime) -> None:
        """`start_after`: where a consumer that has never run begins (only bars written after it); once it has committed, its own offset rules."""
        self.conn, self.name, self.start_after = conn, name, start_after

    def _cursor(self) -> tuple[datetime, int, datetime]:
        row = self.conn.execute(
            "SELECT built_at, instrument_id, ts FROM consumer_offset WHERE consumer=%s",
            (self.name,),
        ).fetchone()
        if row is None:
            return (self.start_after, -1, datetime.min.replace(tzinfo=self.start_after.tzinfo))
        return (row[0], int(row[1]), row[2])

    def poll(self, limit: int = 500) -> list[Delivered]:
        """The next bars after the offset, oldest write first. Nothing is consumed until `commit`."""
        rows = self.conn.execute(
            "SELECT instrument_id, ts, open, high, low, close, volume, partial, built_at FROM live_bar_1m"
            " WHERE (built_at, instrument_id, ts) > (%s, %s, %s) ORDER BY built_at, instrument_id, ts LIMIT %s",
            (*self._cursor(), limit),
        ).fetchall()
        return [Delivered(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows]

    def commit(self, rows: list[Delivered], now: datetime) -> None:
        if not rows:
            return
        last = max(rows, key=lambda r: (r.built_at, r.instrument_id, r.ts))
        self.conn.execute(
            "INSERT INTO consumer_offset (consumer, built_at, instrument_id, ts, updated_at) VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (consumer) DO UPDATE SET built_at=EXCLUDED.built_at, instrument_id=EXCLUDED.instrument_id,"
            " ts=EXCLUDED.ts, updated_at=EXCLUDED.updated_at",
            (self.name, last.built_at, last.instrument_id, last.ts, now),
        )

    def run_once(
        self, handler: Callable[[list[Delivered]], object], now: datetime, limit: int = 500
    ) -> int:
        """Handle the next bars and move the offset in one transaction: if the handler raises, neither happens. Returns how many bars."""
        with self.conn.transaction():
            rows = self.poll(limit)
            if rows:
                handler(rows)
                self.commit(rows, now)
        return len(rows)


def data_fresh(conn: psycopg.Connection, now: datetime, max_age: timedelta) -> str | None:
    """Why the live data cannot be trusted right now, or None when it can: the feed must be CONNECTED and have written a bar recently.
    A runner that gets a reason must not emit targets (a stale-data guard)."""
    row = conn.execute("SELECT state, last_bar_at FROM feed_status").fetchone()
    if row is None:
        return "there is no feed status"
    state, last = row
    if state != "CONNECTED":
        return f"the feed is {state}"
    if last is None:
        return "the feed has written no bar yet"
    age = now - last
    if age < -CLOCK_TOLERANCE:
        return f"this machine's clock is {int(-age.total_seconds())} s behind the feed's last bar: it cannot tell whether the data is fresh"
    if age > max_age:
        return f"the last bar is {int(age.total_seconds() // 60)} minutes old (limit {int(max_age.total_seconds() // 60)})"
    return None

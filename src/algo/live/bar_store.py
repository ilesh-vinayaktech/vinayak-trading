# ruff: noqa: E501
"""Where live bars and the feed's heartbeat are kept (migration 033). A bar is written once; every new one is announced
on the Postgres channel `live_bar` as "<instrument_id>,<minute open>" so a strategy runner can wake on it instead of polling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import psycopg

from algo.live.bars import LiveBar
from algo.live.ticks import Tick

CHANNEL = "live_bar"


def token_map(conn: psycopg.Connection) -> dict[int, int]:
    """Kite instrument token -> our instrument id, for the instruments we could match and that are in today's mapping."""
    rows = conn.execute(
        "SELECT instrument_token, instrument_id FROM kite_instrument WHERE instrument_id IS NOT NULL AND active"
    ).fetchall()
    return {int(t): int(i) for t, i in rows}


def save_bars(
    conn: psycopg.Connection, bars: Sequence[LiveBar], ids: Mapping[int, int], now: datetime
) -> int:
    """Store the bars of instruments we know; returns how many were new. Re-sending a bar changes nothing."""
    new = 0
    for b in bars:
        iid = ids.get(b.token)
        if iid is None:
            continue
        n = conn.execute(
            "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (iid, b.ts, b.open, b.high, b.low, b.close, b.volume, b.ticks, b.partial, now),
        ).rowcount
        if n:
            conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, f"{iid},{b.ts.isoformat()}"))
            new += n
    return new


def save_status(
    conn: psycopg.Connection,
    state: str,
    detail: str,
    *,
    subscribed: int,
    last_tick_at: datetime | None,
    last_bar_at: datetime | None,
    ticks: int,
    bars: int,
    bad_frames: int,
    late_ticks: int,
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO feed_status (feed_id, state, detail, subscribed, last_tick_at, last_bar_at, ticks_total, bars_total, bad_frames, late_ticks, updated_at)"
        " VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (feed_id) DO UPDATE SET state=EXCLUDED.state, detail=EXCLUDED.detail, subscribed=EXCLUDED.subscribed,"
        " last_tick_at=EXCLUDED.last_tick_at, last_bar_at=EXCLUDED.last_bar_at, ticks_total=EXCLUDED.ticks_total,"
        " bars_total=EXCLUDED.bars_total, bad_frames=EXCLUDED.bad_frames, late_ticks=EXCLUDED.late_ticks, updated_at=EXCLUDED.updated_at",
        (
            state,
            detail,
            subscribed,
            last_tick_at,
            last_bar_at,
            ticks,
            bars,
            bad_frames,
            late_ticks,
            now,
        ),
    )


def read_status(conn: psycopg.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT state, detail, subscribed, last_tick_at, last_bar_at, ticks_total, bars_total, bad_frames, late_ticks, updated_at FROM feed_status"
    ).fetchone()
    if row is None:
        return None
    keys = (
        "state",
        "detail",
        "subscribed",
        "last_tick_at",
        "last_bar_at",
        "ticks",
        "bars",
        "bad_frames",
        "late_ticks",
        "updated_at",
    )
    return dict(zip(keys, row, strict=True))


QUOTE_KEYS = (
    "ltp",
    "day_open",
    "day_high",
    "day_low",
    "prev_close",
    "volume",
    "exchange_ts",
    "updated_at",
    "minute_ts",
    "minute_open",
    "minute_high",
    "minute_low",
    "minute_volume",
)
UPSERT_QUOTE = (
    "INSERT INTO live_quote (instrument_id, ltp, day_open, day_high, day_low, prev_close, volume, exchange_ts, updated_at,"
    " minute_ts, minute_open, minute_high, minute_low, minute_volume) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    " ON CONFLICT (instrument_id) DO UPDATE SET ltp=EXCLUDED.ltp,"
    " day_open=COALESCE(EXCLUDED.day_open, live_quote.day_open), day_high=COALESCE(EXCLUDED.day_high, live_quote.day_high),"
    " day_low=COALESCE(EXCLUDED.day_low, live_quote.day_low), prev_close=COALESCE(EXCLUDED.prev_close, live_quote.prev_close),"
    " volume=COALESCE(EXCLUDED.volume, live_quote.volume), exchange_ts=COALESCE(EXCLUDED.exchange_ts, live_quote.exchange_ts),"
    " updated_at=EXCLUDED.updated_at, minute_ts=EXCLUDED.minute_ts, minute_open=EXCLUDED.minute_open,"
    " minute_high=EXCLUDED.minute_high, minute_low=EXCLUDED.minute_low, minute_volume=EXCLUDED.minute_volume"
)


def save_quotes(
    conn: psycopg.Connection,
    quotes: Mapping[int, Tick],
    ids: Mapping[int, int],
    now: datetime,
    minutes: Mapping[int, LiveBar] | None = None,
) -> int:
    """Replace each followed stock's latest quote in place, in one batch; returns how many rows were written. A tick that
    carries no day figures, volume or exchange time (a price-only packet) keeps the ones already stored. `minutes` is the
    minute each stock is still building (BarBuilder.in_progress); a stock without one gets NULLs there."""
    rows = []
    for token, t in quotes.items():
        iid = ids.get(token)
        if iid is None:
            continue
        m = (minutes or {}).get(token)
        rows.append(
            (iid, t.ltp, t.day_open, t.day_high, t.day_low, t.prev_close, t.volume, t.exchange_ts, now,
             *((m.ts, m.open, m.high, m.low, m.volume) if m else (None,) * 5))
        )  # fmt: skip
    if rows:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_QUOTE, rows)
    return len(rows)


def read_quote(conn: psycopg.Connection, instrument_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(QUOTE_KEYS)} FROM live_quote WHERE instrument_id=%s", (instrument_id,)
    ).fetchone()
    return None if row is None else dict(zip(QUOTE_KEYS, row, strict=True))

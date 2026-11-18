# ruff: noqa: E501
"""Where the live index quotes and 1-minute index bars are kept (migration 104), and how the dashboard cards read them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import psycopg

from algo.data.providers.kite import Candle
from algo.live.bars import MINUTE, LiveBar
from algo.live.ticks import Tick

# The indices the feed follows, by the name Kite and `index_bar_1d` use; shown in this order. Their tokens come from index_bar_1d.
TRACKED = (
    ("NSE", "NIFTY 50"),
    ("BSE", "SENSEX"),
    ("NSE", "INDIA VIX"),
    ("NSE", "NIFTY BANK"),
    ("NSE", "NIFTY FIN SERVICE"),
    ("NSE", "NIFTY IT"),
    ("NSE", "NIFTY MIDCAP 100"),
    ("NSE", "NIFTY SMLCAP 100"),
    ("NSE", "NIFTY 500"),
)


def index_tokens(conn: psycopg.Connection) -> dict[int, tuple[str, str]]:
    """Kite token -> (exchange, symbol) of every tracked index, from the newest daily row that carries its token."""
    out: dict[int, tuple[str, str]] = {}
    for exchange, symbol in TRACKED:
        row = conn.execute(
            "SELECT token FROM index_bar_1d WHERE exchange=%s AND symbol=%s AND token IS NOT NULL ORDER BY trade_date DESC LIMIT 1",
            (exchange, symbol),
        ).fetchone()
        if row is not None:
            out[int(row[0])] = (exchange, symbol)
    return out


def save_index_quotes(
    conn: psycopg.Connection,
    quotes: Mapping[int, Tick],
    names: Mapping[int, tuple[str, str]],
    now: datetime,
) -> int:
    """Replace each followed index's latest quote in place; a tick without the day's figures keeps the ones stored."""
    rows = [
        (tok, *names[tok], t.ltp, t.day_open, t.day_high, t.day_low, t.prev_close, t.exchange_ts, now)
        for tok, t in quotes.items()
        if tok in names
    ]  # fmt: skip
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO index_live_quote (token, exchange, symbol, ltp, day_open, day_high, day_low, prev_close, exchange_ts, updated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (token) DO UPDATE SET ltp=EXCLUDED.ltp,"
                " day_open=COALESCE(EXCLUDED.day_open, index_live_quote.day_open), day_high=COALESCE(EXCLUDED.day_high, index_live_quote.day_high),"
                " day_low=COALESCE(EXCLUDED.day_low, index_live_quote.day_low), prev_close=COALESCE(EXCLUDED.prev_close, index_live_quote.prev_close),"
                " exchange_ts=COALESCE(EXCLUDED.exchange_ts, index_live_quote.exchange_ts), updated_at=EXCLUDED.updated_at",
                rows,
            )
    return len(rows)


def save_index_bars(
    conn: psycopg.Connection,
    bars: Sequence[LiveBar],
    names: Mapping[int, tuple[str, str]],
    now: datetime,
    source: str = "live",
) -> int:
    """Store finished minutes of followed indices; a minute already stored is left alone (the first writer wins). Returns how many were new."""
    new = 0
    for b in bars:
        if b.token not in names:
            continue
        cur = conn.execute(
            "INSERT INTO index_bar_1m (token, exchange, symbol, ts, open, high, low, close, source, built_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (b.token, *names[b.token], b.ts, b.open, b.high, b.low, b.close, source, now),
        )
        new += cur.rowcount
    return new


def read_cards(
    conn: psycopg.Connection, day_start: datetime, day_end: datetime
) -> list[dict[str, Any]]:
    """The latest quote of every tracked index (in TRACKED order) with today's minute closes for a sparkline; an index never seen is left out."""
    quotes = {
        (e, s): (ltp, o, h, lo, pc, ts, upd)
        for e, s, ltp, o, h, lo, pc, ts, upd in conn.execute(
            "SELECT exchange, symbol, ltp, day_open, day_high, day_low, prev_close, exchange_ts, updated_at FROM index_live_quote"
        )
    }
    spark: dict[tuple[str, str], list[float]] = {}
    for e, s, c in conn.execute(
        "SELECT exchange, symbol, close::float8 FROM index_bar_1m WHERE ts >= %s AND ts < %s ORDER BY ts", (day_start, day_end)
    ):  # fmt: skip
        spark.setdefault((e, s), []).append(c)
    out = []
    for key in TRACKED:
        q = quotes.get(key)
        if q is None:
            continue
        ltp, o, h, lo, pc, ts, upd = q
        out.append({"exchange": key[0], "symbol": key[1], "ltp": ltp, "day_open": o, "day_high": h, "day_low": lo, "prev_close": pc, "exchange_ts": ts, "updated_at": upd, "spark": spark.get(key, [])})  # fmt: skip
    return out


class Historical(Protocol):
    def historical(
        self, instrument_token: int, interval: str, start: datetime, end: datetime
    ) -> list[Candle]: ...


def load_kite_minutes(
    conn: psycopg.Connection,
    client: Historical,
    names: Mapping[int, tuple[str, str]],
    start: datetime,
    end: datetime,
    now: datetime,
) -> int:
    """Fill index minutes from Kite's own 1-minute candles between `start` and `end` (what the feed missed, or days before it ran). A minute already stored
    is kept as it is. Returns the number of new minutes."""
    new = 0
    for token in names:
        candles = client.historical(token, "minute", start, end)
        bars = [
            LiveBar(token, c.ts, c.open, c.high, c.low, c.close, 0, 0, True)
            for c in candles
            if c.ts + MINUTE <= now
        ]  # a minute still building is not final
        new += save_index_bars(conn, bars, names, now, source="kite")
    return new

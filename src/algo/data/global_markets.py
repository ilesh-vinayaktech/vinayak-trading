# ruff: noqa: E501
"""Global closes for the morning forecast: US index closes and the US VIX from Yahoo Finance's chart endpoint (unofficial, no key: it can change without notice, so a payload
that does not parse is an error, never a guess), and GIFT Nifty at 08:45 IST from Kite minute candles. Stored in `global_daily`."""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import psycopg

IST = ZoneInfo("Asia/Kolkata")
YAHOO = {"SP500": "^GSPC", "NASDAQ": "^IXIC", "VIXUS": "^VIX"}
GIFT = "GIFT0845"
GIFT_AT = time(
    8, 45
)  # the morning reading: GIFT Nifty trades long before the Indian open, this is what a trader sees at breakfast


def yahoo_url(symbol: str, start: date, end: date) -> str:
    p1 = int(datetime.combine(start, time(0), UTC).timestamp())
    p2 = int(datetime.combine(end, time(23, 59), UTC).timestamp())
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?period1={p1}&period2={p2}&interval=1d"


def parse_yahoo(raw: bytes) -> list[tuple[date, float]]:
    """(date, close) per session, oldest first, the date being the market's own local date. Sessions with no close are skipped; raises ValueError on a payload that is not a chart."""
    try:
        result = json.loads(raw)["chart"]["result"][0]
        stamps, closes = result["timestamp"], result["indicators"]["quote"][0]["close"]
        offset = int(result["meta"].get("gmtoffset", 0))
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"yahoo chart payload not understood: {e!r}") from e
    from datetime import timedelta

    return [
        (
            datetime.fromtimestamp(t, UTC).date()
            if offset == 0
            else (datetime.fromtimestamp(t, UTC) + timedelta(seconds=offset)).date(),
            float(c),
        )
        for t, c in zip(stamps, closes, strict=True)
        if c
    ]


def gift_reading(candles: Sequence[tuple[datetime, float]]) -> list[tuple[date, float]]:
    """One (day, price) per IST day from minute candles (timestamp, close): the candle that opens at 08:45 IST."""
    return [
        (ts.astimezone(IST).date(), px)
        for ts, px in candles
        if ts.astimezone(IST).time().replace(second=0, microsecond=0) == GIFT_AT
    ]


def store(
    conn: psycopg.Connection,
    symbol: str,
    rows: Sequence[tuple[date, float]],
    source: str,
    now: datetime,
) -> int:
    """Upsert one close per day; returns the rows written."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO global_daily (symbol, day, close, source, ingested_at) VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (symbol, day) DO UPDATE SET close=EXCLUDED.close, source=EXCLUDED.source, ingested_at=EXCLUDED.ingested_at",
            [(symbol, d, c, source, now) for d, c in rows],
        )
    return len(rows)


def series(conn: psycopg.Connection, symbol: str) -> list[tuple[date, float]]:
    return [
        (d, float(c))
        for d, c in conn.execute(
            "SELECT day, close FROM global_daily WHERE symbol=%s ORDER BY day", (symbol,)
        ).fetchall()
    ]


def last_session_return(rows: Sequence[tuple[date, float]], before: date) -> float | None:
    """The return, in %, of the last session dated before `before` against the session before it: what has happened overnight when India opens on `before`. None without two sessions."""
    prior = [r for r in rows if r[0] < before]
    if len(prior) < 2 or prior[-2][1] == 0:
        return None
    return 100.0 * (prior[-1][1] / prior[-2][1] - 1)

# ruff: noqa: E501
"""Kite DAILY candles of every NSE/BSE index into index_bar_1d (no volume: indexes have none). Resumable by design:
upsert on (exchange, symbol, trade_date), so a re-run only refreshes. Pure of the system clock: `now` is injected."""

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg

from algo.data.providers.kite import Candle, windows

IST = ZoneInfo("Asia/Kolkata")
NOT_INDEXES = ("BHARATBOND", "-NAV")  # bond ETF / NAV rows Kite files under INDICES
ALSO = (
    "GOLDBEES",
)  # an NSE-listed gold ETF kept beside the indexes: the market zone's gold signal (the same daily candles, no volume used)


class Historical(Protocol):
    def historical(
        self, instrument_token: int, interval: str, start: datetime, end: datetime
    ) -> list[Candle]: ...


@dataclass
class IndexLoad:
    rows: int = 0
    empty: int = 0
    dropped: int = 0


def index_rows(raw: bytes) -> list[tuple[int, str, str]]:
    """(token, exchange, symbol) of the NSE and BSE indexes in the Kite instrument dump."""
    return [
        (int(r["instrument_token"]), r["exchange"], r["tradingsymbol"])
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8")))
        if (
            r["segment"] == "INDICES"
            and r["exchange"] in ("NSE", "BSE")
            and not any(x in r["tradingsymbol"] for x in NOT_INDEXES)
        )
        or (r["segment"] == "NSE" and r["exchange"] == "NSE" and r["tradingsymbol"] in ALSO)
    ]


def load_index_days(
    conn: psycopg.Connection,
    client: Historical,
    rows: list[tuple[int, str, str]],
    start: date,
    end: date,
    now: datetime,
) -> IndexLoad:
    res = IndexLoad()
    for token, exchange, symbol in rows:
        got = 0
        for ws, we in windows(start, end, 2000):
            candles = client.historical(
                token,
                "day",
                datetime.combine(ws, time(0, 0), IST),
                datetime.combine(we, time(23, 59, 59), IST),
            )
            real = [
                c for c in candles if c.close > 0
            ]  # no close = unusable (Kite pads before a launch; a few old rows have a zero close)
            res.dropped += len(candles) - len(real)
            for c in real:
                conn.execute(
                    "INSERT INTO index_bar_1d (exchange, symbol, trade_date, open, high, low, close, token, ingested_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (exchange, symbol, trade_date) DO UPDATE SET"
                    " open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, ingested_at=EXCLUDED.ingested_at",
                    (
                        exchange,
                        symbol,
                        c.ts.astimezone(IST).date(),
                        c.open,
                        c.high,
                        c.low,
                        c.close,
                        token,
                        now.astimezone(UTC),
                    ),
                )
            got += len(real)
        res.rows += got
        res.empty += got == 0
    return res

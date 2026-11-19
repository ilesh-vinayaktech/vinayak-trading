# ruff: noqa: E501
"""Candles for one index, in the same shape the stock charts use, so the same chart draws them: daily from the Kite daily candles (`index_bar_1d`, some back to 1990), weekly and monthly rolled up from them,
and intraday built at read time from the stored one-minute bars (`index_bar_1m`, written by the live feed, so intraday history starts the day the feed first followed the index). Indexes carry no volume:
every bar says 0 and the chart's volume pane stays empty. Nothing is adjusted (an index has no splits or dividends of its own)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from algo.api.queries import INTRADAY_MINUTES
from algo.data.bars import Bar
from algo.data.reader import IST
from algo.data.resample import resample, resample_calendar

CALENDAR = {"1w": "week", "1mo": "month"}
DEFAULT_INTRADAY_DAYS = 5
MAX_INTRADAY_DAYS = 120
ZERO = Decimal(0)


def _row(b: Bar, intraday: bool) -> dict[str, Any]:
    day = b.ts.astimezone(IST).date().isoformat()
    out: dict[str, Any] = {
        "date": day,
        "open": str(b.open),
        "high": str(b.high),
        "low": str(b.low),
        "close": str(b.close),
        "volume": "0",
        "factor": "1",
    }
    if intraday:
        out["time"] = int(b.ts.astimezone(UTC).timestamp())
    return out


def index_bars(
    conn: psycopg.Connection, symbol: str, timeframe: str, start: date | None, end: date | None
) -> dict[str, Any] | None:
    """Bars of `timeframe` between `start` and `end` (inclusive) for the index `symbol`, or None when no such index has candles. The answer also says the daily extent and where intraday history begins."""
    ex = conn.execute(
        "SELECT exchange, min(trade_date), max(trade_date) FROM index_bar_1d WHERE symbol=%s GROUP BY exchange ORDER BY (exchange='NSE') DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if ex is None:
        return None
    exchange, first, last = ex
    first_minute = conn.execute(
        "SELECT min((ts AT TIME ZONE 'Asia/Kolkata')::date), max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM index_bar_1m WHERE exchange=%s AND symbol=%s",
        (exchange, symbol),
    ).fetchone()
    intraday = timeframe in INTRADAY_MINUTES
    if not intraday and timeframe != "1d" and timeframe not in CALENDAR:
        raise ValueError(f"unknown timeframe {timeframe}")
    last_minute = (
        first_minute[1] if first_minute and first_minute[1] else last
    )  # intraday ends on the newest stored minute day by default (no clock is read here)
    stop = end or (last_minute if intraday else last)
    if intraday:
        begin = max(
            start or stop - timedelta(days=DEFAULT_INTRADAY_DAYS),
            stop - timedelta(days=MAX_INTRADAY_DAYS),
        )
        rows = conn.execute(
            "SELECT ts, open, high, low, close FROM index_bar_1m WHERE exchange=%s AND symbol=%s AND ts >= %s AND ts < %s ORDER BY ts",
            (
                exchange,
                symbol,
                datetime.combine(begin, time(0), IST),
                datetime.combine(stop + timedelta(days=1), time(0), IST),
            ),
        ).fetchall()
        bars = resample(
            [Bar(symbol, r[0], r[1], r[2], r[3], r[4], ZERO) for r in rows],
            INTRADAY_MINUTES[timeframe],
        )
    else:
        begin = start or stop - timedelta(days=365)
        rows = conn.execute(
            "SELECT trade_date, open, high, low, close FROM index_bar_1d WHERE exchange=%s AND symbol=%s AND trade_date BETWEEN %s AND %s ORDER BY trade_date",
            (exchange, symbol, begin, stop),
        ).fetchall()
        daily = [
            Bar(symbol, datetime.combine(r[0], time(0), IST), r[1], r[2], r[3], r[4], ZERO)
            for r in rows
        ]
        bars = resample_calendar(daily, CALENDAR[timeframe]) if timeframe in CALENDAR else daily
    return {
        "symbol": symbol,
        "exchange": exchange,
        "timeframe": timeframe,
        "first": first.isoformat(),
        "last": last.isoformat(),
        "intraday_first": None
        if first_minute is None or first_minute[0] is None
        else first_minute[0].isoformat(),
        "bars": [_row(b, intraday) for b in bars],
    }

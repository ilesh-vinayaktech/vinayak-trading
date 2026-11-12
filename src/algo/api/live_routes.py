# ruff: noqa: E501
"""The live price of one stock for the charts: the latest quote the feed published, and whether the feed is really live.

Read-only and polled every couple of seconds by the Data Explorer. Prices leave as decimal strings (never floats)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from algo.api import queries
from algo.api.security import PortalSettings, WConn
from algo.data.bars import Bar
from algo.live.bar_store import read_quote, read_status
from algo.live.candle import intraday_candle, period_candle, today_bar
from algo.live.market_calendar import IST

router = APIRouter(prefix="/api/live", tags=["live"])
SILENT_AFTER = timedelta(seconds=30)  # a connected feed with no tick for this long is not live


def _s(d: Decimal | int | None) -> str | None:
    return None if d is None else format(Decimal(d).normalize(), "f")


Timeframe = Literal[
    "1m", "3m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "3h", "4h", "1d", "1w", "1mo"
]
Adjust = Literal["none", "split", "total_return"]
PERIODS = {"1w": "week", "1mo": "month"}


def _period_start(day: date, period: str) -> date:
    return day.replace(day=1) if period == "month" else day - timedelta(days=day.weekday())


def _candle(
    conn: WConn, instrument_id: int, q: dict[str, Any], timeframe: str, adjust: str
) -> dict[str, Any] | None:
    """The candle still forming for this chart timeframe: built from the quote's day, this period's stored daily bars, or
    today's finished live minutes plus the minute still being built."""
    day = q["updated_at"].astimezone(IST).date()
    if timeframe in queries.INTRADAY_MINUTES:
        open_ = datetime.combine(day, time(0), IST)
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM live_bar_1m WHERE instrument_id=%s AND ts >= %s AND ts < %s ORDER BY ts",
            (instrument_id, open_, open_ + timedelta(days=1)),
        ).fetchall()
        done = [Bar("live", *r) for r in rows]
        building = (
            Bar(
                "live",
                q["minute_ts"],
                q["minute_open"],
                q["minute_high"],
                q["minute_low"],
                q["ltp"],
                Decimal(q["minute_volume"] or 0),
            )
            if q["minute_ts"] is not None and q["minute_ts"].astimezone(IST).date() == day
            else None
        )
        c = intraday_candle(done, building, queries.INTRADAY_MINUTES[timeframe])
        return None if c is None else _shown(c, int(c.ts.astimezone(UTC).timestamp()))
    today = today_bar(
        day,
        ltp=q["ltp"],
        day_open=q["day_open"],
        day_high=q["day_high"],
        day_low=q["day_low"],
        volume=q["volume"],
    )
    if timeframe == "1d":
        return _shown(today, day.isoformat())
    period = PERIODS[timeframe]
    start, yesterday = _period_start(day, period), day - timedelta(days=1)
    stored = (
        queries.reader_for(conn, instrument_id)[0]
        .issuer_history(instrument_id, start, yesterday, adjust=adjust)
        .bars
        if start <= yesterday
        else []
    )
    c = period_candle(
        [Bar("stored", b.ts, b.open, b.high, b.low, b.close, b.volume) for b in stored],
        today,
        period,
    )
    return _shown(c, c.ts.astimezone(IST).date().isoformat())


def _shown(c: Bar, when: int | str) -> dict[str, Any]:
    return {
        "time": when,
        "open": _s(c.open),
        "high": _s(c.high),
        "low": _s(c.low),
        "close": _s(c.close),
        "volume": _s(c.volume),
    }


@router.get("/{instrument_id}")
def live(
    instrument_id: int,
    request: Request,
    conn: WConn,
    timeframe: Timeframe = "1d",
    adjust: Adjust = "none",
) -> dict[str, Any]:
    if queries.instrument(conn, instrument_id) is None:
        raise HTTPException(404, f"no instrument {instrument_id}")
    st: PortalSettings = request.app.state.portal
    now = st.clock.now()
    feed = read_status(conn)
    q = read_quote(conn, instrument_id)
    last_tick = feed["last_tick_at"] if feed else None
    on = bool(
        q
        and feed
        and feed["state"] == "CONNECTED"
        and last_tick is not None
        and now - last_tick <= SILENT_AFTER
    )
    return {
        "today": now.astimezone(IST).date().isoformat(),
        "candle": None if q is None else _candle(conn, instrument_id, q, timeframe, adjust),
        "live": on,
        "feed": {
            "state": feed["state"] if feed else None,
            "last_tick_at": last_tick.isoformat() if last_tick else None,
        },
        "session_date": q["updated_at"].astimezone(IST).date().isoformat() if q else None,
        "quote": None
        if q is None
        else {
            "ltp": _s(q["ltp"]),
            "open": _s(q["day_open"]),
            "high": _s(q["day_high"]),
            "low": _s(q["day_low"]),
            "prev_close": _s(q["prev_close"]),
            "volume": _s(q["volume"]),
            "updated_at": q["updated_at"].isoformat(),
        },
    }

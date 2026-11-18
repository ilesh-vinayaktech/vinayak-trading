# ruff: noqa: E501
"""The live price of one stock for the charts: the latest quote the feed published, and whether the feed is really live.

Read-only and polled every couple of seconds by the Data Explorer. Prices leave as decimal strings (never floats)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from algo.api import queries
from algo.api.security import CurrentUser, PortalSettings, WConn
from algo.data.bars import Bar
from algo.live.bar_store import read_quote, read_status
from algo.live.candle import intraday_candle, period_candle, today_bar
from algo.live.index_store import CARDS, read_cards
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


def _change(ltp: Decimal | None, prev: Decimal | None) -> tuple[str | None, float | None]:
    if ltp is None or prev is None or prev == 0:
        return None, None
    return _s(ltp - prev), float((ltp - prev) / prev * 100)


@router.get("/indices")
def indices(request: Request, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """The cards at the top of the Overview: Nifty 50, Sensex, India VIX and the other tracked indices with today's change and a minute-by-minute line.
    An index the feed has not quoted shows its last two daily closes instead (`source` says which)."""
    now = request.app.state.portal.clock.now()
    day = now.astimezone(IST).date()
    start = datetime.combine(day, time(0), IST)
    cards = {
        (c["exchange"], c["symbol"]): c for c in read_cards(conn, start, start + timedelta(days=1))
    }
    out = []
    for ex, sym in CARDS:
        c = cards.get((ex, sym))
        if c is not None:
            change, pct = _change(c["ltp"], c["prev_close"])
            out.append({"exchange": ex, "symbol": sym, "source": "live", "ltp": _s(c["ltp"]), "prev_close": _s(c["prev_close"]), "change": change, "change_pct": pct, "day_high": _s(c["day_high"]), "day_low": _s(c["day_low"]), "as_of": c["updated_at"].isoformat(), "spark": c["spark"]})  # fmt: skip
            continue
        rows = conn.execute(
            "SELECT trade_date, close FROM index_bar_1d WHERE exchange=%s AND symbol=%s ORDER BY trade_date DESC LIMIT 2", (ex, sym)
        ).fetchall()  # fmt: skip
        if rows:
            change, pct = _change(rows[0][1], rows[1][1] if len(rows) > 1 else None)
            out.append({"exchange": ex, "symbol": sym, "source": "daily", "ltp": _s(rows[0][1]), "prev_close": _s(rows[1][1]) if len(rows) > 1 else None, "change": change, "change_pct": pct, "day_high": None, "day_low": None, "as_of": rows[0][0].isoformat(), "spark": []})  # fmt: skip
    feed = read_status(conn)
    last_tick = feed["last_tick_at"] if feed else None
    live = bool(
        feed
        and feed["state"] == "CONNECTED"
        and last_tick is not None
        and now - last_tick <= SILENT_AFTER
    )
    return {"live": live, "indices": out}


MAX_QUOTES = 500


@router.get("/quotes")
def quotes(ids: str, who: CurrentUser, conn: WConn) -> dict[str, Any]:
    """The latest price of up to 500 stocks, for the lists everywhere in the portal (`ids` is comma separated instrument ids). A stock the feed has not quoted
    shows its last daily close (`source` 'close'); one with neither is left out."""
    try:
        want = sorted({int(x) for x in ids.split(",") if x.strip()})[:MAX_QUOTES]
    except ValueError:
        raise HTTPException(400, "ids must be integers separated by commas") from None
    out: dict[str, Any] = {}
    for iid, ltp, prev, upd in conn.execute(
        "SELECT instrument_id, ltp, prev_close, updated_at FROM live_quote WHERE instrument_id = ANY(%s)", (want,)
    ):  # fmt: skip
        change, pct = _change(ltp, prev)
        out[str(iid)] = {"ltp": _s(ltp), "prev_close": _s(prev), "change": change, "change_pct": pct, "source": "live", "as_of": upd.isoformat()}  # fmt: skip
    rest = [i for i in want if str(i) not in out]
    if rest:
        last: dict[int, list[tuple[Any, Decimal]]] = {}
        for iid, ts, close in conn.execute(
            "SELECT instrument_id, ts, close FROM (SELECT DISTINCT ON (instrument_id, ts) instrument_id, ts, close, row_number() OVER (PARTITION BY instrument_id ORDER BY ts DESC) rn"
            " FROM bar_1d WHERE instrument_id = ANY(%s) AND source='nse' AND ts >= now() - interval '15 days' ORDER BY instrument_id, ts DESC, dataset_version DESC) x WHERE rn <= 2", (rest,)
        ):  # fmt: skip
            last.setdefault(iid, []).append((ts, close))
        for iid, rows in last.items():
            rows.sort(reverse=True)
            change, pct = _change(rows[0][1], rows[1][1] if len(rows) > 1 else None)
            out[str(iid)] = {"ltp": _s(rows[0][1]), "prev_close": _s(rows[1][1]) if len(rows) > 1 else None, "change": change, "change_pct": pct, "source": "close", "as_of": rows[0][0].isoformat()}  # fmt: skip
    return {"quotes": out}


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

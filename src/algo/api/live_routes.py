# ruff: noqa: E501
"""The live price of one stock for the charts: the latest quote the feed published, and whether the feed is really live.

Read-only and polled every couple of seconds by the Data Explorer. Prices leave as decimal strings (never floats)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from algo.api import queries
from algo.api.security import PortalSettings, WConn
from algo.live.bar_store import read_quote, read_status
from algo.live.market_calendar import IST

router = APIRouter(prefix="/api/live", tags=["live"])
SILENT_AFTER = timedelta(seconds=30)  # a connected feed with no tick for this long is not live


def _s(d: Decimal | int | None) -> str | None:
    return None if d is None else format(Decimal(d).normalize(), "f")


@router.get("/{instrument_id}")
def live(instrument_id: int, request: Request, conn: WConn) -> dict[str, Any]:
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

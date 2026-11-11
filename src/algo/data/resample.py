# ruff: noqa: E501
"""Build any intraday or daily timeframe from stored 1-minute bars (the only intraday base we keep).

Buckets are anchored to the NSE session open (09:15 IST), so 15m bars start 09:15, 09:30 ... and 60m bars 09:15, 10:15 ...
(the broker convention); a bucket holds whatever minutes exist (missing minutes are not invented). minutes=0 means one bar
per IST trading day. Input: one instrument's bars, any order. Output ts = bucket open, UTC. Pure: no I/O, no clock."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from algo.data.bars import Bar

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)


def _bucket(ts: datetime, minutes: int) -> datetime:
    local = ts.astimezone(IST)
    open_ = datetime.combine(local.date(), SESSION_OPEN, IST)
    if minutes == 0:
        return open_.astimezone(UTC)
    offset = int((local - open_).total_seconds() // 60)
    return (open_ + timedelta(minutes=offset // minutes * minutes)).astimezone(UTC)


def resample(bars: Iterable[Bar], minutes: int) -> list[Bar]:
    if minutes < 0:
        raise ValueError("minutes must be >= 0 (0 = daily)")
    out: dict[datetime, Bar] = {}
    for b in sorted(bars, key=lambda x: x.ts):
        k = _bucket(b.ts, minutes)
        cur = out.get(k)
        if cur is None:
            out[k] = Bar(b.symbol, k, b.open, b.high, b.low, b.close, b.volume)
        else:
            out[k] = Bar(
                cur.symbol,
                k,
                cur.open,
                max(cur.high, b.high),
                min(cur.low, b.low),
                b.close,
                cur.volume + b.volume,
            )
    return list(out.values())


def resample_calendar(bars: Iterable[Bar], period: str) -> list[Bar]:
    """Daily bars into weekly (Monday-Friday) or monthly bars. Each is dated by its first trading day, which keeps the
    chart's day-based time axis. Input is one instrument's already-adjusted daily bars; adjustment is not redone."""
    if period not in ("week", "month"):
        raise ValueError("period must be 'week' or 'month'")
    out: dict[tuple[int, ...], Bar] = {}
    for b in sorted(bars, key=lambda x: x.ts):
        day = b.ts.astimezone(IST).date()
        key = (day.year, day.month) if period == "month" else day.isocalendar()[:2]
        cur = out.get(key)
        if cur is None:
            out[key] = b
        else:
            out[key] = Bar(
                cur.symbol,
                cur.ts,
                cur.open,
                max(cur.high, b.high),
                min(cur.low, b.low),
                b.close,
                cur.volume + b.volume,
            )
    return list(out.values())

"""Clocks. Strategies and services never call the system clock; they get a Clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


def require_utc(ts: datetime) -> datetime:
    """Reject naive datetimes; normalise to UTC."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("naive datetime not allowed; use tz-aware")
    return ts.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    """Manually advanced, monotonic clock for backtest/replay/tests."""

    def __init__(self, start: datetime) -> None:
        self._now = require_utc(start)

    def now(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime) -> None:
        ts = require_utc(ts)
        if ts < self._now:
            raise ValueError("clock cannot move backwards")
        self._now = ts

    def advance(self, delta: timedelta) -> None:
        self.advance_to(self._now + delta)

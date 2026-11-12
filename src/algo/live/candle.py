# ruff: noqa: E501
"""The candle still forming on a chart, for any timeframe, from what the live feed knows now (pure: no I/O, no clock).

  today_bar        today's daily candle: the exchange's own day open/high/low and the last price (widened to it)
  period_candle    this week's or month's candle: the stored daily bars of the period so far plus today, rolled up the same
                   way the chart's weekly/monthly bars are (resample_calendar: dated by the period's first trading day)
  intraday_candle  the current N-minute bar: today's finished live minutes plus the minute still being built, bucketed
                   from 09:15 IST like every other intraday bar (resample)
A stored bar for today is dropped in favour of the live one, and a building minute that has already finished is not counted
twice, so nothing is double counted."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal

from algo.data.bars import Bar
from algo.data.resample import IST, resample, resample_calendar

SESSION_OPEN = time(9, 15)


def today_bar(
    day: date,
    *,
    ltp: Decimal,
    day_open: Decimal | None,
    day_high: Decimal | None,
    day_low: Decimal | None,
    volume: int | None,
) -> Bar:
    o = day_open if day_open is not None else ltp
    h = max(day_high if day_high is not None else ltp, ltp, o)
    lo = min(day_low if day_low is not None else ltp, ltp, o)
    ts = datetime.combine(day, SESSION_OPEN, IST).astimezone(UTC)
    return Bar("live", ts, o, h, lo, ltp, Decimal(volume or 0))


def period_candle(daily: Sequence[Bar], today: Bar, period: str) -> Bar:
    """`daily`: the period's stored daily bars (any may be from before the period; they are dropped)."""
    day = today.ts.astimezone(IST).date()
    key = (day.year, day.month) if period == "month" else day.isocalendar()[:2]

    def same_period(b: Bar) -> bool:
        d = b.ts.astimezone(IST).date()
        return d != day and ((d.year, d.month) if period == "month" else d.isocalendar()[:2]) == key

    rolled = resample_calendar([*filter(same_period, daily), today], period)
    return rolled[-1]  # every input is in the one period


def intraday_candle(minutes: Sequence[Bar], building: Bar | None, every: int) -> Bar | None:
    done = {m.ts for m in minutes}
    all_minutes = [
        *minutes,
        *([building] if building is not None and building.ts not in done else []),
    ]
    if not all_minutes:
        return None
    return max(resample(all_minutes, every), key=lambda b: b.ts)

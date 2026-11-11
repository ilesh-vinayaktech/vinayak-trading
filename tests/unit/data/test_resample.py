from datetime import UTC, datetime
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from algo.data.bars import Bar
from algo.data.resample import resample

IST = ZoneInfo("Asia/Kolkata")


def m(day: int, hh: int, mm: int, o, h, low, c, v) -> Bar:
    ts = datetime(2026, 11, day, hh, mm, tzinfo=IST).astimezone(UTC)
    return Bar("X", ts, D(str(o)), D(str(h)), D(str(low)), D(str(c)), D(str(v)))


def hm(b: Bar) -> str:
    return b.ts.astimezone(IST).strftime("%H:%M")


def test_fifteen_minute_buckets_start_at_the_session_open_and_combine_ohlcv():
    bars = [m(10, 9, 29, 12, 13, 11, 12.5, 5), m(10, 9, 15, 10, 11, 9, 10.5, 1), m(10, 9, 16, 10.5, 15, 10, 14, 2), m(10, 9, 30, 20, 21, 19, 20, 7)]  # fmt: skip
    out = resample(bars, 15)  # unsorted input is fine
    assert [(hm(b), b.open, b.high, b.low, b.close, b.volume) for b in out] == [
        ("09:15", D(10), D(15), D(9), D("12.5"), D(8)),
        ("09:30", D(20), D(21), D(19), D(20), D(7)),
    ]
    assert out[0].ts.utcoffset().total_seconds() == 0 and out[0].symbol == "X"


def test_sixty_minute_buckets_follow_the_09_15_anchor_and_missing_minutes_are_not_invented():
    out = resample(
        [m(10, 9, 15, 1, 2, 1, 2, 1), m(10, 10, 14, 2, 3, 2, 3, 1), m(10, 10, 15, 5, 6, 5, 6, 1)],
        60,
    )
    assert [hm(b) for b in out] == ["09:15", "10:15"]


def test_zero_minutes_gives_one_bar_per_trading_day():
    out = resample(
        [m(10, 9, 15, 1, 2, 1, 2, 1), m(10, 15, 29, 2, 9, 0.5, 8, 4), m(11, 9, 15, 8, 8, 8, 8, 1)],
        0,
    )
    assert [(b.ts.astimezone(IST).day, b.open, b.high, b.low, b.close, b.volume) for b in out] == [
        (10, D(1), D(9), D("0.5"), D(8), D(5)),
        (11, D(8), D(8), D(8), D(8), D(1)),
    ]
    assert out[0].ts == datetime(2026, 11, 10, 3, 45, tzinfo=UTC)  # 09:15 IST


def test_empty_input_and_negative_minutes():
    assert resample([], 5) == []
    with pytest.raises(ValueError):
        resample([], -1)


def d(day: int, month: int, o, h, low, c, v) -> Bar:
    ts = datetime(2026, month, day, 9, 15, tzinfo=IST).astimezone(UTC)
    return Bar("X", ts, D(str(o)), D(str(h)), D(str(low)), D(str(c)), D(str(v)))


def test_weekly_bars_run_monday_to_friday_and_are_dated_by_their_first_trading_day():
    from algo.data.resample import resample_calendar

    # Tue 3 Nov starts a short week (Mon 2 Nov was a holiday); Mon 9 Nov starts the next
    bars = [
        d(4, 11, 12, 15, 11, 14, 5),
        d(3, 11, 10, 11, 9, 11, 3),
        d(6, 11, 14, 14, 8, 9, 2),
        d(9, 11, 9, 20, 9, 19, 7),
    ]
    out = resample_calendar(bars, "week")
    assert [
        (b.ts.astimezone(IST).date().isoformat(), b.open, b.high, b.low, b.close, b.volume)
        for b in out
    ] == [
        ("2026-11-03", D(10), D(15), D(8), D(9), D(10)),
        ("2026-11-09", D(9), D(20), D(9), D(19), D(7)),
    ]


def test_monthly_bars_group_by_calendar_month_and_bad_period_is_refused():
    from algo.data.resample import resample_calendar

    out = resample_calendar(
        [d(30, 10, 1, 2, 1, 2, 1), d(2, 11, 2, 5, 2, 4, 1), d(30, 11, 4, 9, 3, 8, 2)], "month"
    )
    assert [(b.ts.astimezone(IST).date().isoformat(), b.open, b.close, b.volume) for b in out] == [
        ("2026-10-30", D(1), D(2), D(1)),
        ("2026-11-02", D(2), D(8), D(3)),
    ]
    assert resample_calendar([], "week") == []
    with pytest.raises(ValueError):
        resample_calendar([], "year")

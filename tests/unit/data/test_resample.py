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

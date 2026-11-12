"""The candle still forming, for any chart timeframe, from what the feed knows now."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from algo.data.bars import Bar
from algo.live.candle import intraday_candle, period_candle, today_bar

THU = date(2026, 11, 12)  # a Thursday
OPEN = datetime(2026, 11, 12, 3, 45, tzinfo=UTC)  # 09:15 IST


def day(d: date, o, h, low, c, v=100) -> Bar:
    return Bar(
        "X", datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC), D(o), D(h), D(low), D(c), D(v)
    )


def minute(m: int, o, h, low, c, v=10) -> Bar:
    return Bar("X", OPEN + timedelta(minutes=m), D(o), D(h), D(low), D(c), D(v))


def test_todays_candle_takes_the_exchanges_day_figures_and_the_last_price():
    b = today_bar(THU, ltp=D(105), day_open=D(100), day_high=D(108), day_low=D(97), volume=5000)
    assert (b.ts, b.open, b.high, b.low, b.close, b.volume) == (
        OPEN,
        D(100),
        D(108),
        D(97),
        D(105),
        D(5000),
    )


def test_todays_candle_widens_to_the_last_price_and_starts_from_it_when_the_day_figures_are_missing():
    b = today_bar(THU, ltp=D(110), day_open=D(100), day_high=D(108), day_low=D(97), volume=None)
    assert (b.high, b.volume) == (D(110), D(0))
    bare = today_bar(THU, ltp=D(50), day_open=None, day_high=None, day_low=None, volume=None)
    assert (bare.open, bare.high, bare.low, bare.close) == (D(50), D(50), D(50), D(50))


def test_the_week_so_far_plus_today_is_this_weeks_candle_dated_by_its_first_trading_day():
    mon, tue, wed = THU - timedelta(days=3), THU - timedelta(days=2), THU - timedelta(days=1)
    week = [
        day(mon, 100, 104, 99, 103, 10),
        day(tue, 103, 110, 101, 108, 20),
        day(wed, 108, 109, 95, 96, 30),
    ]
    today = today_bar(THU, ltp=D(98), day_open=D(96), day_high=D(100), day_low=D(94), volume=40)
    c = period_candle(week, today, "week")
    assert (c.ts.date(), c.open, c.high, c.low, c.close, c.volume) == (
        mon,
        D(100),
        D(110),
        D(94),
        D(98),
        D(100),
    )


def test_last_weeks_bars_do_not_leak_into_this_weeks_candle_and_monday_starts_a_new_one():
    last_fri = THU - timedelta(days=6)
    today = today_bar(
        THU - timedelta(days=3), ltp=D(10), day_open=D(9), day_high=D(11), day_low=D(8), volume=5
    )  # Monday
    c = period_candle([day(last_fri, 50, 60, 40, 55)], today, "week")
    assert (c.ts.date(), c.open, c.high, c.low, c.close, c.volume) == (
        THU - timedelta(days=3),
        D(9),
        D(11),
        D(8),
        D(10),
        D(5),
    )


def test_a_stored_bar_for_today_is_replaced_by_the_live_one_not_counted_twice():
    stale_today = day(THU, 100, 101, 99, 100, 999)
    today = today_bar(THU, ltp=D(103), day_open=D(100), day_high=D(104), day_low=D(99), volume=50)
    c = period_candle([stale_today], today, "month")
    assert (c.ts.date(), c.close, c.high, c.volume) == (THU, D(103), D(104), D(50))


def test_the_month_so_far_plus_today_is_this_months_candle():
    first = date(2026, 11, 2)  # the month's first trading day
    month = [
        day(first, 200, 210, 190, 205, 1),
        day(date(2026, 10, 30), 1, 1, 1, 1, 1),
    ]  # October is left out
    today = today_bar(THU, ltp=D(215), day_open=D(205), day_high=D(220), day_low=D(204), volume=2)
    c = period_candle(month, today, "month")
    assert (c.ts.date(), c.open, c.high, c.low, c.close, c.volume) == (
        first,
        D(200),
        D(220),
        D(190),
        D(215),
        D(3),
    )


def test_the_current_intraday_bar_merges_finished_minutes_with_the_one_still_building():
    done = [
        minute(0, 100, 101, 99, 100),
        minute(1, 100, 103, 100, 102),
        minute(5, 102, 102, 101, 101),
    ]
    building = minute(6, 101, 104, 100, 103, 7)
    c = intraday_candle(
        done, building, 5
    )  # the 09:20 bar holds 09:20 (done) and 09:21 (still building)
    assert (c.ts, c.open, c.high, c.low, c.close, c.volume) == (
        OPEN + timedelta(minutes=5),
        D(102),
        D(104),
        D(100),
        D(103),
        D(17),
    )


def test_a_building_minute_already_finished_is_not_counted_twice_and_one_minute_bars_are_that_minute():
    done = [minute(0, 100, 101, 99, 100, 10)]
    c = intraday_candle(done, minute(0, 100, 101, 99, 100, 10), 1)
    assert (c.ts, c.volume) == (OPEN, D(10))
    assert intraday_candle([], minute(3, 7, 8, 6, 7, 1), 1).ts == OPEN + timedelta(minutes=3)


def test_no_minutes_at_all_means_no_intraday_candle():
    assert intraday_candle([], None, 15) is None

from datetime import UTC, date, datetime, time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algo.core.calendar import SessionCalendar, nse

HOL = {date(2026, 1, 26)}  # Tue (test data, not authoritative)
CAL = nse(HOL)


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def test_nse_day_has_375_bars_starting_0915_ist():
    bars = CAL.session_bars(date(2026, 1, 5))
    assert len(bars) == 375
    assert bars[0] == utc(2026, 1, 5, 3, 45) and bars[-1] == utc(2026, 1, 5, 9, 59)


def test_15m_bars_25_per_day():
    assert len(CAL.session_bars(date(2026, 1, 5), 15)) == 25


def test_weekend_and_holiday_closed():
    for d in (date(2026, 1, 3), date(2026, 1, 4), date(2026, 1, 26)):
        assert not CAL.is_trading_day(d) and CAL.session(d) is None and CAL.session_bars(d) == []


def test_is_open_boundaries():
    assert not CAL.is_open(utc(2026, 1, 5, 3, 44))
    assert CAL.is_open(utc(2026, 1, 5, 3, 45))
    assert CAL.is_open(utc(2026, 1, 5, 9, 59))
    assert not CAL.is_open(utc(2026, 1, 5, 10, 0))  # 15:30 IST close is exclusive
    assert not CAL.is_open(utc(2026, 1, 3, 5, 0))  # Saturday


def test_next_boundary_within_day_and_rollover():
    assert CAL.next_bar_boundary(utc(2026, 1, 5, 3, 45)) == utc(2026, 1, 5, 3, 46)
    assert CAL.next_bar_boundary(utc(2026, 1, 5, 3, 0)) == utc(2026, 1, 5, 3, 45)
    # after last bar Mon -> Tue 09:15 IST ; Fri -> Mon
    assert CAL.next_bar_boundary(utc(2026, 1, 5, 9, 59)) == utc(2026, 1, 6, 3, 45)
    assert CAL.next_bar_boundary(utc(2026, 1, 23, 9, 59)) == utc(2026, 1, 27, 3, 45)


def test_prev_session_skips_weekend_and_holiday():
    assert CAL.prev_session(date(2026, 1, 5)) == date(2026, 1, 2)
    assert CAL.prev_session(date(2026, 1, 27)) == date(2026, 1, 23)


def test_special_session_on_weekend():
    d = date(2026, 11, 8)  # Sunday
    c = nse(special={d: (time(18, 0), time(19, 0))})
    assert c.is_trading_day(d) and len(c.session_bars(d)) == 60
    assert c.session(d) == (utc(2026, 11, 8, 12, 30), utc(2026, 11, 8, 13, 30))


def test_naive_rejected():
    with pytest.raises(ValueError):
        CAL.is_open(datetime(2026, 1, 5, 4))  # noqa: DTZ001


def test_no_holiday_data_guard():
    all_closed = SessionCalendar(
        "Asia/Kolkata",
        time(9, 15),
        time(15, 30),
        [date(2026, 1, 1) + timedelta(days=i) for i in range(500)],
    )
    with pytest.raises(RuntimeError):
        all_closed.next_bar_boundary(utc(2026, 1, 1))


@given(
    st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31)),  # noqa: DTZ001
    st.sampled_from([1, 5, 15]),
)
def test_next_boundary_property(naive, m):
    ts = naive.replace(tzinfo=UTC)
    b = CAL.next_bar_boundary(ts, m)
    assert b > ts and CAL.is_open(b)
    assert b in CAL.session_bars(b.astimezone(CAL.tz).date(), m)


def test_session_times_do_not_depend_on_the_machine_timezone(monkeypatch):
    """The exchange zone, not the host zone, defines the session (a bug here only shows up when the
    code runs on a machine that is not set to IST)."""
    import time as _time

    monkeypatch.setenv("TZ", "America/New_York")
    _time.tzset()
    try:
        cal = nse()
        assert cal.session(date(2026, 1, 5)) == (utc(2026, 1, 5, 3, 45), utc(2026, 1, 5, 10, 0))
        assert cal.session_bars(date(2026, 1, 5))[0] == utc(2026, 1, 5, 3, 45)
        assert cal.is_open(utc(2026, 1, 5, 3, 45)) and not cal.is_open(utc(2026, 1, 5, 3, 44))
    finally:
        monkeypatch.undo()
        _time.tzset()

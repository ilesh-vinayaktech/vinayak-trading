from datetime import UTC, datetime, timedelta, timezone

import pytest

from algo.core.clock import SimClock, SystemClock, require_utc

T0 = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)


def test_naive_rejected():
    with pytest.raises(ValueError, match="^naive datetime not allowed; use tz-aware$"):
        require_utc(datetime(2026, 1, 5))  # noqa: DTZ001
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 5))  # noqa: DTZ001


def test_normalises_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert require_utc(datetime(2026, 1, 5, 9, 15, tzinfo=ist)) == T0


def test_simclock_advances_and_never_goes_back():
    c = SimClock(T0)
    c.advance(timedelta(minutes=1))
    assert c.now() == T0 + timedelta(minutes=1)
    c.advance_to(c.now())  # same time is allowed
    with pytest.raises(ValueError):
        c.advance_to(T0)


def test_systemclock_is_tz_aware():
    assert SystemClock().now().tzinfo is not None


def test_result_is_really_in_utc_not_merely_an_equal_instant():
    ist = timezone(timedelta(hours=5, minutes=30))
    out = require_utc(datetime(2026, 1, 5, 9, 15, tzinfo=ist))
    assert out.tzinfo is UTC and out.utcoffset() == timedelta(0) and out.hour == 3


def test_a_tzinfo_that_cannot_give_an_offset_is_rejected_like_a_naive_datetime():
    from datetime import tzinfo

    class Unknown(tzinfo):
        def utcoffset(self, dt):
            return None

        def dst(self, dt):
            return None

    with pytest.raises(ValueError, match="naive"):
        require_utc(datetime(2026, 1, 5, tzinfo=Unknown()))


def test_simclock_refuses_to_go_backwards_with_a_clear_message():
    c = SimClock(T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="^clock cannot move backwards$"):
        c.advance_to(T0)

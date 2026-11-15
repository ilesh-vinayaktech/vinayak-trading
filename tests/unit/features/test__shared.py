from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from algo.features._shared import SessionBar, latest, q, window

DAYS = [date(2026, 1, 5) + timedelta(days=i) for i in range(5)]


def bar(day, hours=0):
    return SessionBar(
        day, D(1), D(1), D(1), D(1), D(1), datetime(2026, 1, 5, tzinfo=UTC) + timedelta(hours=hours)
    )


def test_q_rounds_half_to_even_at_twelve_decimals():
    assert q(D("0.0000000000005")) == D("0")  # exactly half: to the even neighbour
    assert q(D("0.0000000000015")) == D("0.000000000002")
    assert str(q(D("1.5"))) == "1.500000000000"


def test_window_is_the_n_bars_ending_at_the_session_oldest_first_and_none_on_any_gap():
    bars = {d: bar(d) for d in DAYS}
    assert [b.day for b in window(DAYS, 3, 3, bars)] == DAYS[1:4]
    assert window(DAYS, 1, 3, bars) is None  # fewer than n sessions so far
    del bars[DAYS[2]]
    assert (
        window(DAYS, 3, 3, bars) is None and window(DAYS, 4, 2, bars) is not None
    )  # a gap inside the window only


def test_latest_is_the_slowest_input():
    assert latest([bar(DAYS[0], 5), bar(DAYS[1], 50), bar(DAYS[2], 10)]) == datetime(
        2026, 1, 5, tzinfo=UTC
    ) + timedelta(hours=50)

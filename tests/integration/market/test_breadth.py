# ruff: noqa: E501
"""Market breadth from daily bars, on synthetic stocks with known answers: a stock that rises every day, one that falls, a flat one, one too illiquid to count and one
too new to have a 50-day average."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.market.breadth import daily_breadth
from tests.support.bt import put_bars

pytestmark = pytest.mark.integration
N = 300
LAST = date(2026, 11, 13)  # a Friday


def weekdays(n=N, end=LAST):
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


DAYS = weekdays()


def price(x):
    return D(str(round(x, 4)))


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {s: repo.add_instrument(x, s) for s in "ABCDE"}
    put_bars(
        conn, ids["A"], {d: price(100 * 1.002**i) for i, d in enumerate(DAYS)}
    )  # rises every day
    put_bars(
        conn, ids["B"], {d: price(100 * 0.998**i) for i, d in enumerate(DAYS)}
    )  # falls every day
    put_bars(conn, ids["C"], {d: price(100) for d in DAYS})  # flat
    put_bars(
        conn, ids["D"], {d: price(100 * 1.002**i) for i, d in enumerate(DAYS)}, vol=1
    )  # too thin to count
    put_bars(
        conn, ids["E"], {d: price(100 * 1.002**i) for i, d in enumerate(DAYS[-40:])}
    )  # listed 40 days ago
    return conn, ids


def test_each_days_counts_on_known_stocks(env):
    conn, _ = env
    last = daily_breadth(conn, DAYS[0])[-1]
    assert last.day == LAST
    assert last.universe == 4  # D is too thin
    assert (last.advancers, last.decliners, last.unchanged) == (
        2,
        1,
        1,
    )  # A and E rose, B fell, C is flat
    assert (last.n50, last.above50) == (
        3,
        1,
    )  # E has 40 days, so it is not in the base; only A is above its average
    assert (last.n200, last.above200) == (3, 1)
    assert (last.highs, last.lows) == (1, 1)  # A broke out, B broke down, the flat stock is neither
    assert round(last.pct_above_50 or 0, 1) == 33.3 and round(last.pct_above_200 or 0, 1) == 33.3


def test_a_day_with_too_little_history_has_no_average_base_and_no_percentage(env):
    conn, _ = env
    early = daily_breadth(conn, DAYS[0])[0]
    assert (
        early.n50 == 0
        and early.pct_above_50 is None
        and early.n200 == 0
        and early.pct_above_200 is None
    )


def test_asking_for_a_window_gives_the_same_numbers_for_those_days(env):
    conn, _ = env
    full = {b.day: b for b in daily_breadth(conn, DAYS[0])}
    part = daily_breadth(conn, DAYS[-5], DAYS[-2])
    assert [b.day for b in part] == DAYS[-5:-1]
    assert all(b == full[b.day] for b in part)  # the lookback makes the averages identical

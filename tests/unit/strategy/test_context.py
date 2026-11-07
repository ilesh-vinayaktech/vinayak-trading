from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.reader import Loaded
from algo.strategy.context import Context, DataAccess, PortfolioView

OPEN = lambda d: datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)  # noqa: E731
VISIBLE = timedelta(hours=9, minutes=15)
DAYS = [date(2025, 6, 9), date(2025, 6, 10), date(2025, 6, 11)]


def loaded(prices):
    rows = [(OPEN(d), D(p), D(p), D(p), D(p), D(100)) for d, p in zip(DAYS, prices, strict=True)]
    return Loaded(rows, [], VISIBLE, strict=False)


def test_portfolio_view_is_read_only_and_drops_zero_positions():
    v = PortfolioView.of(D(5), {1: D(10), 2: D(0)}, D(100))
    assert dict(v.positions) == {1: D(10)}
    with pytest.raises(TypeError):
        v.positions[3] = D(1)  # type: ignore[index]


def test_history_is_bounded_by_the_clock_and_a_bar_appears_only_after_it_is_published():
    clock = SimClock(datetime(2025, 6, 10, 12, 59, tzinfo=UTC))
    da = DataAccess({1: loaded((100, 101, 102))}, clock, "none")
    # 10 Jun 12:59Z: the 10 Jun bar needs until 13:00Z, so only 9 Jun is visible
    assert [b.close for b in da.history([1], 30)[1]] == [D(100)]
    clock.advance_to(datetime(2025, 6, 10, 13, 0, tzinfo=UTC))
    assert [b.close for b in da.history([1], 30)[1]] == [D(100), D(101)]  # 11 Jun never visible


def test_lookback_window_and_unknown_instruments():
    clock = SimClock(datetime(2025, 6, 11, 13, 0, tzinfo=UTC))
    da = DataAccess({1: loaded((100, 101, 102))}, clock, "none")
    assert [b.close for b in da.history([1], 1)[1]] == [D(101), D(102)]  # 10 Jun and 11 Jun
    assert da.history([1, 999], 30).keys() == {1}  # unknown ids are simply absent


def test_context_exposes_clock_mode_portfolio_and_no_database_handle():
    clock = SimClock(datetime(2025, 6, 11, 13, 0, tzinfo=UTC))
    ctx = Context(clock, DataAccess({}, clock, "split"), PortfolioView.of(D(1), {}, D(1)), "strict")
    assert ctx.now() == clock.now() and ctx.mode == "strict" and ctx.portfolio.cash == D(1)
    assert not any(hasattr(ctx, n) for n in ("conn", "db", "broker", "reader"))
    assert not any(hasattr(ctx.data, n) for n in ("conn", "db", "broker", "reader"))

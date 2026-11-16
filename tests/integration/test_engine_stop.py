# ruff: noqa: E501
"""The per-trade stop and the re-entry cooldown inside the backtest, so the strategy that is validated is the one the paper account trades (review 2026-11-16, section 3.9)."""

from decimal import Decimal as D

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.bt import DAYS, ZERO, cfg, put_bars
from tests.support.strategies import HoldParams, Scripted

pytestmark = pytest.mark.integration
PRICES = [
    100,
    100,
    100,
    100,
    97,
    97,
    97,
    97,
    97,
    97,
]  # bought at the 2nd day's open at 100; the 5th close is 3% under the cost


@pytest.fixture
def stock(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    a = repo.add_instrument(repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE"), "AAA")
    put_bars(conn, a, dict(zip(DAYS, map(D, PRICES), strict=True)))
    return conn, a


def run(conn, a, **kw):
    script = (
        [{a: D(1)}] + [None] * 5 + [{a: D(1)}] + [None] * 5
    )  # buy, hold, then ask to buy again two sessions after the stop
    return run_backtest(conn, Scripted(HoldParams(ids=(a,), weights=(D(1),)), script), cfg(**kw))


def sides(res):
    return [(t.day.isoformat(), t.side) for t in res.trades]


def test_without_a_stop_the_position_is_held_through_the_fall(stock):
    conn, a = stock
    assert sides(run(conn, a)) == [("2025-06-03", "BUY")]


def test_a_position_three_percent_under_its_cost_is_sold_at_the_next_open_when_the_limit_is_two_percent(
    stock,
):
    conn, a = stock
    res = run(conn, a, trade_stop=D("0.02"))
    assert (
        sides(res) == [("2025-06-03", "BUY"), ("2025-06-09", "SELL"), ("2025-06-11", "BUY")]
    )  # stopped at the close of the 6th, sold at the 9th's open, the strategy's own re-buy allowed (no cooldown)


def test_during_the_cooldown_the_stopped_name_is_not_bought_back_even_if_the_strategy_asks(stock):
    conn, a = stock
    res = run(conn, a, trade_stop=D("0.02"), stop_cooldown_days=5)
    assert sides(res) == [
        ("2025-06-03", "BUY"),
        ("2025-06-09", "SELL"),
    ]  # asked again 4 days after the stop: still cooling


def test_a_loss_inside_the_limit_is_left_alone_and_the_settings_are_validated(stock):
    conn, a = stock
    assert sides(run(conn, a, trade_stop=D("0.05"))) == [
        ("2025-06-03", "BUY")
    ]  # 3% is inside a 5% limit
    for bad in ({"trade_stop": D(0)}, {"trade_stop": D(1)}, {"stop_cooldown_days": -1}):
        with pytest.raises(ValueError):
            BacktestConfig(start=DAYS[0], end=DAYS[-1], initial_cash=D(1000), cost=ZERO, **bad)

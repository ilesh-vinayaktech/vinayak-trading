# ruff: noqa: E501, F811
"""A strategy that is only data, run by the real backtest engine on the synthetic market. ENGINEERING_TEST_ONLY: synthetic prices.

Callers: pytest. Uses algo.factory (the DSL and the interpreter), the engine, and the market in tests/integration/test_trend_pullback_engine.py.
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test"."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.universe import Interval
from algo.factory import dsl
from algo.factory.interpreter import DslStrategy
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategy.base import Mode
from tests.integration.test_trend_pullback_engine import DAYS, UP, market  # noqa: F401
from tests.support.bt import ZERO

pytestmark = pytest.mark.integration
DEFINITION = {
    "strategy_id": "TREND_UP_001", "version": 1, "description": "Hold the strongest 20-day risers while they stay above their 50-day average.",
    "universe": "MEMBERS", "timeframe": "DAILY",
    "entry": {"all": [{"feature": "ret_20d", "op": ">", "value": 0}, {"feature": "dist_sma_50d", "op": ">", "value": 0}]},
    "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": 0}]},
    "ranking": {"feature": "ret_20d", "order": "DESC"},
    "position": {"max_positions": 5, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 20},
    "rebalance": "WEEKLY",
}  # fmt: skip


def go(conn, ids, unusable=None, mode=Mode.RESEARCH, **over):
    defn = dsl.StrategyDef.model_validate({**DEFINITION, **over})
    members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids], unusable)
    s = DslStrategy(defn, members)
    cfg = BacktestConfig(
        start=DAYS[100], end=DAYS[-1], initial_cash=D(1_000_000), cost=ZERO, mode=mode
    )
    return s, run_backtest(conn, s, cfg)


def test_a_definition_written_as_data_runs_in_the_real_engine_and_does_what_it_says(market):
    conn, ids = market
    s, result = go(conn, ids)
    assert (result.strategy_id, result.strategy_version) == (
        "TREND_UP_001",
        "1",
    ) and result.params_hash == s.defn.sha256[:16]
    assert result.trades, "the scenario must trade"
    falling = set(
        ids[UP:]
    )  # these never rise: ret_20d is negative every day, so the entry rule can never hold
    assert {t.instrument_id for t in result.trades}.isdisjoint(falling)
    assert {t.side for t in result.trades} >= {"BUY"}
    # decisions are made on the first session of a week and filled at the next open: every BUY lands on the day after a Monday decision
    first_week_days = {
        d
        for i, d in enumerate(DAYS)
        if i == 0 or d.isocalendar()[:2] != DAYS[i - 1].isocalendar()[:2]
    }
    buy_days = {t.day for t in result.trades if t.side == "BUY"}
    assert buy_days and all(DAYS[DAYS.index(d) - 1] in first_week_days for d in buy_days)
    assert (
        max(
            len({t.instrument_id for t in result.trades if t.day == d and t.side == "BUY"})
            for d in buy_days
        )
        <= 5
    )


def test_the_same_definition_gives_the_same_result_to_the_bit_and_a_changed_rule_gives_a_different_one(
    market,
):  # noqa: F811
    conn, ids = market
    first = go(conn, ids)[1].result_hash
    assert go(conn, ids)[1].result_hash == first
    assert go(conn, ids, version=2, rebalance="DAILY")[1].result_hash != first
    assert (
        go(conn, ids, version=2, position={"max_positions": 3, "sizing": "EQUAL_WEIGHT"})[
            1
        ].result_hash
        != first
    )


def test_every_decision_leaves_an_audit_row_and_non_rebalance_days_leave_none(market):
    conn, ids = market
    s, result = go(conn, ids)
    days = [r["day"] for r in s.audit]
    weeks = {date.fromisoformat(d).isocalendar()[:2] for d in days}
    assert len(days) == len(weeks)  # one decision per ISO week
    assert all(
        {"members", "ready", "no_bar", "warming_up", "held", "exits", "entries"} <= set(r)
        for r in s.audit
    )
    assert len(result.equity) > len(days)


def test_in_strict_mode_a_day_whose_membership_evidence_is_unusable_makes_no_decision_and_the_rebalance_moves_to_the_next_session(
    market,
):
    conn, ids = market
    first = go(conn, ids)[0].audit[0]["day"]
    s, _ = go(
        conn, ids, unusable={date.fromisoformat(first): "membership not verified"}, mode=Mode.STRICT
    )
    assert s.audit[0] == {
        "day": first,
        "skipped": "strict: membership evidence unusable",
        "reasons": "membership not verified",
    }
    assert (
        s.audit[1]["day"] == str(DAYS[DAYS.index(date.fromisoformat(first)) + 1])
        and "entries" in s.audit[1]
    )  # the same week's decision happens the next session
    research, _ = go(
        conn, ids, unusable={date.fromisoformat(first): "membership not verified"}
    )  # research mode does not refuse on it
    assert research.audit[0]["day"] == first and "entries" in research.audit[0]

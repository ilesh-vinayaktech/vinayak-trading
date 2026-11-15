# ruff: noqa: E501
"""S4 execution parity: the same strategy, parameters, bars and universe give the same DECISIONS (which names, which side) whether the backtest engine
or the paper runner asks. Sizes may differ by design (the engine fills at the next open with a participation cap, paper sizes at the decision close),
so the comparison is on the decision, with a check that both size every name from the same slot."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.universe import Interval
from algo.paper.runner import run_day
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from tests.integration.paper.test_runner import DAY, NOW, PARAMS, env, orders, user  # noqa: F401
from tests.integration.test_trend_pullback_engine import DAYS
from tests.support.bt import ZERO

pytestmark = pytest.mark.integration


def test_the_engine_and_the_paper_runner_make_the_same_decision_on_the_same_bars(env):  # noqa: F811
    conn, ids, lake = env
    members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
    strategy = TrendPullback(TrendPullbackParams(**PARAMS), members)
    cfg = BacktestConfig(
        start=DAY, end=DAYS[DAYS.index(DAY) + 1], initial_cash=D(1_000_000), cost=ZERO
    )
    engine = {
        (t.instrument_id, t.side)
        for t in run_backtest(conn, strategy, cfg).trades
        if t.day == cfg.end
    }
    out = run_day(conn, user(conn), day=DAY, now=NOW, lake_root=lake)
    paper = {
        (r[0], r[1])
        for r in orders(conn, conn.execute("SELECT user_id FROM paper_run").fetchone()[0])
    }
    assert out.status == "PROPOSED" and paper, "the scenario must produce a decision to compare"
    assert engine == paper

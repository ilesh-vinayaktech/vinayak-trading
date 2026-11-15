# ruff: noqa: E501, F811
"""Experiments on strategy definitions, run by the real engine on the synthetic market. ENGINEERING_TEST_ONLY: synthetic prices."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.universe import Interval
from algo.factory import dsl, lab, registry
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from tests.integration.test_trend_pullback_engine import DAYS, market  # noqa: F401
from tests.support.bt import ZERO
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
LOCK = Lock(DAYS[-11], DAYS[-10], DAYS[-1])  # development ends ten sessions before the data does
START, END = (
    DAYS[170],
    DAYS[-11],
)  # a short window keeps the many backtests quick; 50 sessions of warm-up come before it
BASE = dsl.StrategyDef.model_validate(
    {
        "strategy_id": "TREND_UP_001", "version": 1, "description": "Hold the strongest 20-day risers above their 50-day average.",
        "universe": "MEMBERS", "timeframe": "DAILY",
        "entry": {"all": [{"feature": "ret_20d", "op": ">", "value": 0}, {"feature": "dist_sma_50d", "op": ">", "value": 0}]},
        "exit": {"any": [{"feature": "dist_sma_50d", "op": "<", "value": 0}]},
        "ranking": {"feature": "ret_20d", "order": "DESC"},
        "position": {"max_positions": 5, "sizing": "EQUAL_WEIGHT"}, "risk": {"max_position_percent": 20},
        "rebalance": "WEEKLY",
    }
)  # fmt: skip
GRID = {"position.max_positions": [3, 5], "risk.max_position_percent": [20, 33]}


@pytest.fixture
def world(market, monkeypatch, tmp_path):
    conn, ids = market
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    registry.register(conn, BASE, by="jane", reason="first", now=NOW)
    members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
    return conn, members


def go(conn, members, grid=GRID, **kw):
    kw.setdefault("start", START)
    kw.setdefault("end", END)
    return lab.run_experiment(
        conn,
        BASE,
        grid,
        members=members,
        initial_cash=D(1_000_000),
        cost=ZERO,
        by="jane",
        now=NOW,
        **kw,
    )


def trials(conn, exp):
    return conn.execute(
        "SELECT ordinal, status, overrides, definition_sha256, result_hash FROM factory_trial WHERE experiment_id=%s ORDER BY ordinal",
        (exp,),
    ).fetchall()


def test_every_combination_is_run_and_stored_with_its_overrides_hashes_metrics_and_returns(world):
    conn, members = world
    exp = go(conn, members)
    rows = trials(conn, exp)
    assert [(r[0], r[1]) for r in rows] == [(0, "DONE"), (1, "DONE"), (2, "DONE"), (3, "DONE")]
    assert (
        rows[0][2] == {"position.max_positions": 3, "risk.max_position_percent": 20}
        and len({r[3] for r in rows}) == 4
    )
    planned, grid, base = conn.execute(
        "SELECT trials_planned, grid, base_sha256 FROM factory_experiment WHERE experiment_id=%s",
        (exp,),
    ).fetchone()
    assert planned == 4 and grid == GRID and base == BASE.sha256
    metrics, returns = conn.execute(
        "SELECT metrics, returns FROM factory_trial WHERE experiment_id=%s AND ordinal=0", (exp,)
    ).fetchone()
    assert {"sharpe", "cagr", "max_drawdown", "trades"} <= set(metrics) and metrics["trades"] > 0
    assert len(returns) > 100 and all(isinstance(r, float) for r in returns)


def test_running_the_same_experiment_again_reproduces_every_trial_to_the_bit(world):
    conn, members = world
    first, second = go(conn, members), go(conn, members)
    assert first != second
    assert [(r[3], r[4]) for r in trials(conn, first)] == [
        (r[3], r[4]) for r in trials(conn, second)
    ]


def test_the_report_ranks_the_trials_and_counts_every_attempt_not_just_the_finished_ones(world):
    conn, members = world
    exp = go(
        conn, members, {"position.max_positions": [0, 3, 5, 99]}
    )  # 0 and 99 are not valid definitions
    assert [r[1] for r in trials(conn, exp)] == ["SKIPPED", "DONE", "DONE", "SKIPPED"]
    skipped_reason = conn.execute(
        "SELECT reason FROM factory_trial WHERE experiment_id=%s AND ordinal=0", (exp,)
    ).fetchone()[0]
    assert "max_positions" in skipped_reason
    c = lab.report(conn, exp)
    assert c.n_trials == 4 and len(c.ranked) == 2  # four tries, two finished


def test_a_trial_that_cannot_run_is_recorded_as_failed_with_its_reason_and_the_others_still_run(
    world, monkeypatch
):
    conn, members = world
    real = lab.run_backtest
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise DataNotReady("3 of 20 members have no bar on a day")
        return real(*a, **k)

    monkeypatch.setattr(lab, "run_backtest", flaky)
    exp = go(conn, members)
    assert [r[1] for r in trials(conn, exp)] == ["DONE", "FAILED", "DONE", "DONE"]
    assert (
        "no bar"
        in conn.execute(
            "SELECT reason FROM factory_trial WHERE experiment_id=%s AND status='FAILED'", (exp,)
        ).fetchone()[0]
    )
    assert lab.report(conn, exp).n_trials == 4


def test_the_window_may_not_reach_the_holdout_and_nothing_is_stored_when_it_does(world):
    conn, members = world
    with pytest.raises(lab.LabError, match="holdout"):
        go(conn, members, end=DAYS[-5])
    assert conn.execute("SELECT count(*) FROM factory_experiment").fetchone() == (0,)


def test_the_base_must_be_a_registered_version_exactly_as_registered(world):
    conn, members = world
    other = dsl.StrategyDef.model_validate(
        {**BASE.canonical(), "risk": {"max_position_percent": 25}}
    )
    with pytest.raises(lab.LabError, match="registered"):
        lab.run_experiment(
            conn,
            other,
            GRID,
            members=members,
            start=START,
            end=END,
            initial_cash=D(1_000_000),
            cost=ZERO,
            by="jane",
            now=NOW,
        )
    unknown = dsl.StrategyDef.model_validate({**BASE.canonical(), "strategy_id": "NEVER_001"})
    with pytest.raises(lab.LabError, match="registered"):
        lab.run_experiment(
            conn,
            unknown,
            GRID,
            members=members,
            start=START,
            end=END,
            initial_cash=D(1_000_000),
            cost=ZERO,
            by="jane",
            now=NOW,
        )
    assert conn.execute("SELECT count(*) FROM factory_experiment").fetchone() == (0,)


def test_experiments_and_trials_are_never_changed_or_removed(world):
    conn, members = world
    exp = go(conn, members, {"position.max_positions": [3]})
    for sql in (
        "UPDATE factory_trial SET status='FAILED'",
        "DELETE FROM factory_trial",
        "UPDATE factory_experiment SET grid='{}'",
        "DELETE FROM factory_experiment",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
            conn.execute(sql)
    assert len(trials(conn, exp)) == 1


def test_a_report_for_an_experiment_with_no_finished_trial_says_so(world):
    conn, members = world
    exp = go(conn, members, {"position.max_positions": [0]})
    with pytest.raises(lab.LabError, match="no trial finished"):
        lab.report(conn, exp)
    with pytest.raises(lab.LabError, match="no such experiment"):
        lab.report(conn, 999999)


def test_an_experiment_needs_an_author_an_anchored_lock_and_something_to_vary(world, market):
    conn, members = world
    with pytest.raises(lab.LabError, match="who ran it"):
        lab.run_experiment(
            conn,
            BASE,
            GRID,
            members=members,
            start=START,
            end=END,
            initial_cash=D(1_000_000),
            cost=ZERO,
            by="  ",
            now=NOW,
        )
    with pytest.raises(lab.LabError, match="nothing to vary"):
        go(conn, members, {})
    with pytest.raises(lab.LabError, match="more than 3 combinations"):
        go(conn, members, GRID, max_trials=3)
    assert conn.execute("SELECT count(*) FROM factory_experiment").fetchone() == (0,)


def test_without_an_anchored_research_lock_no_experiment_runs(market):
    conn, ids = market
    members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
    with pytest.raises(lab.LabError, match="research is locked"):
        lab.run_experiment(
            conn,
            BASE,
            GRID,
            members=members,
            start=START,
            end=END,
            initial_cash=D(1_000_000),
            cost=ZERO,
            by="jane",
            now=NOW,
        )

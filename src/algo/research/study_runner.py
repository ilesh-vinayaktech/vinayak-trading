# ruff: noqa: E501
"""Run a registered study's trials: every parameter combination of its grid, one after another, through the real engine.

For each combination: the strategy (looked up in the strategy registry) is built from the study's own settings and run over
the study's RESEARCH window only (from its start to the day before the holdout); prices come from the frozen Kite history,
costs from the stored broker schedules plus the study's slippage, and the stocks from the AMFI segments in force each day.
The trial is saved (metrics and daily returns) and counted in the registry, which is what the deflated Sharpe uses later.
The holdout is never read here. A run is resumable: combinations already done are skipped, a failed one is tried again.
It stops at the first failure and says why; nothing is retried silently."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import psycopg

from algo.backtest import store
from algo.backtest.costs import schedule_store
from algo.backtest.costs.policy import CostPolicy, ScheduleCosts
from algo.backtest.costs.slippage import SlippageModel
from algo.backtest.engine import BacktestConfig, RunResult, run_backtest
from algo.backtest.validation import registry
from algo.backtest.validation.stats import sharpe_per_period
from algo.data.reader import BarReader
from algo.research import study_jobs, study_universe
from algo.research.study import StudySpec
from algo.research.study_store import get_study
from algo.strategies.registry import STRATEGIES
from algo.strategies.trend_pullback import clear_indicator_cache

ALLOWED_COSTS = (
    "verified",
    "extracted_unverified",
    "assumed_backfill",
)  # the study records which statuses it relied on


class StudyRunError(ValueError):
    pass


def cost_policy(conn: psycopg.Connection, spec: StudySpec) -> CostPolicy:
    s = spec.slippage
    return ScheduleCosts(
        schedule_store.load_book(conn, spec.broker, ALLOWED_COSTS),
        SlippageModel(
            base_bps=s.base_bps,
            participation_bps_per_pct=s.participation_bps_per_pct,
            volatility_fraction=s.volatility_fraction,
        ),
        product=spec.product,
        name=f"{spec.broker}-{spec.product.lower()}",
    )


def _returns(r: RunResult) -> list[float]:
    vals = [float(v) for _, v in r.equity]
    return [b / a - 1 for a, b in zip(vals, vals[1:], strict=False) if a > 0]


def _metrics(r: RunResult, returns: list[float]) -> dict[str, Any]:
    return {**{k: v for k, v in r.metrics.items()}, "trades": len(r.trades), "costs": float(sum(t.cost for t in r.trades)), "days": len(r.equity),
            "sharpe_per_period": sharpe_per_period(returns)}  # fmt: skip


def run_study(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """Execute one queued (or claimed) run to the end. Never raises for a trial's own failure: the run records it."""
    run = study_jobs.get_run(conn, run_id)
    if run is None:
        raise StudyRunError(f"no such run {run_id}")
    if run["status"] not in ("QUEUED", "RUNNING"):
        return  # cancelled, or already finished
    exp = run["experiment_id"]
    study = get_study(conn, exp)
    assert study is not None
    spec = StudySpec.model_validate(study["spec"])
    cls, params_cls = STRATEGIES[spec.strategy_id]
    try:
        research_end = spec.holdout_start - timedelta(days=1)
        registry.assert_research_window(conn, exp, research_end)
        membership, coverage = study_universe.build(conn, spec.universe, spec.start, research_end)
        if not membership.ever():
            raise StudyRunError(
                "no stocks to trade: the chosen segments hold none we have Kite history for in this period"
            )
        first = membership.first_day()
        assert first is not None  # the universe is not empty
        begin = max(spec.start, first)  # nothing can be decided before anyone is a member
        policy = cost_policy(conn, spec)
        reader = BarReader(conn, source="kite", publish_lag=timedelta(0))
        combos = study["combinations"]
        already = study_jobs.done_hashes(conn, exp)
        todo = [c for c in combos if registry.params_hash(c) not in already]
        study_jobs.start(
            conn,
            run_id,
            len(combos),
            len(combos) - len(todo),
            {
                "universe_coverage": coverage,
                "research_window": [begin.isoformat(), research_end.isoformat()],
            },
            now,
        )
        clear_indicator_cache()  # a study run never serves a value computed under an earlier adjustment
        for k, combo in enumerate(todo):
            study_jobs.progress(
                conn,
                run_id,
                len(combos) - len(todo) + k,
                ", ".join(f"{n} {v}" for n, v in sorted(combo.items())),
            )
            params_hash = registry.params_hash(combo)
            t0 = time.monotonic()
            try:
                cfg = BacktestConfig(
                    start=begin, end=research_end, initial_cash=spec.capital, cost=policy
                )
                result = run_backtest(
                    conn, cls(params_cls(**combo), membership), cfg, reader=reader
                )
            except Exception as e:  # recorded with its reason, never retried silently
                study_jobs.save_trial(
                    conn,
                    exp,
                    combo,
                    params_hash,
                    "FAILED",
                    now,
                    error=f"{type(e).__name__}: {e}",
                    seconds=time.monotonic() - t0,
                )
                raise StudyRunError(
                    f"{', '.join(f'{n} {v}' for n, v in sorted(combo.items()))}: {type(e).__name__}: {e}"
                ) from e
            returns = _returns(result)
            backtest_run = store.save_run(conn, result, now)
            registry.record_trial(conn, exp, combo, sharpe_per_period(returns), backtest_run, now)
            study_jobs.save_trial(
                conn,
                exp,
                combo,
                params_hash,
                "DONE",
                now,
                metrics=_metrics(result, returns),
                returns=returns,
                backtest_run=backtest_run,
                seconds=time.monotonic() - t0,
            )
        study_jobs.progress(conn, run_id, len(combos), None)
        study_jobs.finish(conn, run_id, "DONE", now)
    except StudyRunError as e:
        study_jobs.finish(conn, run_id, "FAILED", now, str(e))

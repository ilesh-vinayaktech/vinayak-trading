# ruff: noqa: E501
"""The experiment runner (plan.md section 8): run every combination of a grid over a registered strategy definition through the real backtest engine,
over development days only, and keep every trial.

Callers: tests/integration/factory/test_lab.py and the factory scripts. Reads strategy_definition and the research lock; writes factory_experiment and
factory_trial (migration 080, insert-only). User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and
@plan.md ... keep things finishing with test".

  * The base must be a REGISTERED version, byte for byte (same hash): an experiment on something unregistered could not be reproduced.
  * The window may not reach the global research holdout, and prices come through the guarded reader, which cannot return a holdout day.
  * Nothing is stored unless the experiment is valid; once it is, all of it is stored in one transaction. A combination that is not a valid definition is
    SKIPPED, one that errors while running is FAILED with its reason, and both count as tries in the report.
  * The report ranks the finished trials and judges the best against the number of tries (algo.factory.experiment.compare)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.costs.policy import CostPolicy
from algo.backtest.engine import BacktestConfig, RunResult, run_backtest
from algo.backtest.metrics import metrics as equity_metrics
from algo.core.clock import require_utc
from algo.data.reader import BarReader, PriceReader
from algo.factory import experiment, registry
from algo.factory.dsl import StrategyDef
from algo.factory.interpreter import DslStrategy
from algo.research import holdout_lock
from algo.research.holdout_lock import ResearchReader
from algo.strategies.nifty200_momentum import IntervalMembership


class LabError(Exception):
    pass


def _returns(result: RunResult) -> list[float]:
    values = [float(v) for _, v in result.equity]
    return [b / a - 1 for a, b in zip(values, values[1:], strict=False) if a > 0]


def run_experiment(
    conn: psycopg.Connection,
    base: StrategyDef,
    grid: Mapping[str, Sequence[Any]],
    *,
    members: IntervalMembership,
    start: date,
    end: date,
    initial_cash: Decimal,
    cost: CostPolicy,
    by: str,
    now: datetime,
    max_trials: int = 64,
    reader: PriceReader | None = None,
) -> int:
    """Returns the experiment id."""
    if not by.strip():
        raise LabError("an experiment needs who ran it")
    now = require_utc(now)
    try:
        lock = holdout_lock.require(conn)
    except holdout_lock.HoldoutError as e:
        raise LabError(f"research is locked: {e}") from e
    if end > lock.development_end:
        raise LabError(
            f"the window ends {end}, inside the global research holdout (development ends {lock.development_end})"
        )
    try:
        stored = registry.get(conn, base.strategy_id, base.version)
    except registry.RegistryError as e:
        raise LabError(f"the base must be a registered version ({e}): register it first") from e
    if stored.sha256 != base.sha256:
        raise LabError(
            f"the base is not the registered {base.strategy_id} version {base.version} (its hash differs): experiments run on registered versions only"
        )
    try:
        ok, skipped = experiment.variants(base, grid, max_trials)
    except experiment.ExperimentError as e:
        raise LabError(str(e)) from e
    price_reader = reader or ResearchReader(BarReader.for_env(conn), lock)
    cfg = BacktestConfig(start=start, end=end, initial_cash=initial_cash, cost=cost)
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO factory_experiment (base_strategy_id, base_version, base_sha256, grid, window_start, window_end, trials_planned, created_by, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING experiment_id",
            (
                base.strategy_id,
                base.version,
                base.sha256,
                Jsonb({k: list(v) for k, v in grid.items()}),
                start,
                end,
                experiment.trial_count(ok, skipped),
                by.strip(),
                now,
            ),
        ).fetchone()
        assert row is not None
        exp = int(row[0])
        for s in skipped:
            conn.execute(
                "INSERT INTO factory_trial (experiment_id, ordinal, overrides, status, reason, created_at) VALUES (%s,%s,%s,'SKIPPED',%s,%s)",
                (exp, s.index, Jsonb(s.overrides), s.reason, now),
            )
        for v in ok:
            try:
                result = run_backtest(conn, DslStrategy(v.defn, members), cfg, reader=price_reader)
            except Exception as e:  # recorded with its type, never swallowed: a trial that cannot run is still a try
                conn.execute(
                    "INSERT INTO factory_trial (experiment_id, ordinal, overrides, status, reason, definition_sha256, created_at) VALUES (%s,%s,%s,'FAILED',%s,%s,%s)",
                    (
                        exp,
                        v.index,
                        Jsonb(v.overrides),
                        f"{type(e).__name__}: {e}",
                        v.defn.sha256,
                        now,
                    ),
                )
                continue
            metrics: dict[str, Any] = {
                **equity_metrics(result.equity),
                "trades": len(result.trades),
                "final_equity": str(result.equity[-1][1]),
            }
            conn.execute(
                "INSERT INTO factory_trial (experiment_id, ordinal, overrides, status, definition_sha256, metrics, result_hash, returns, created_at) VALUES (%s,%s,%s,'DONE',%s,%s,%s,%s,%s)",
                (
                    exp,
                    v.index,
                    Jsonb(v.overrides),
                    v.defn.sha256,
                    Jsonb(metrics),
                    result.result_hash,
                    Jsonb(_returns(result)),
                    now,
                ),
            )
    return exp


def report(conn: psycopg.Connection, experiment_id: int) -> experiment.Comparison:
    head = conn.execute(
        "SELECT trials_planned FROM factory_experiment WHERE experiment_id=%s", (experiment_id,)
    ).fetchone()
    if head is None:
        raise LabError(f"no such experiment {experiment_id}")
    rows = conn.execute(
        "SELECT overrides, definition_sha256, metrics, result_hash, returns FROM factory_trial WHERE experiment_id=%s AND status='DONE' ORDER BY ordinal",
        (experiment_id,),
    ).fetchall()
    if not rows:
        raise LabError(f"no trial finished in experiment {experiment_id}")
    done = [experiment.TrialResult(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    return experiment.compare(done, attempts=int(head[0]))

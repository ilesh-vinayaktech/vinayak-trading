"""Pre-registration and the trial counter. A hypothesis, its parameter ranges and a holdout window
are written down BEFORE any trial; every distinct configuration tried is counted (that N feeds the
Deflated Sharpe); the holdout can be opened exactly once."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.validation.gates import Evidence, Report
from algo.core.clock import require_utc


class RegistryError(Exception):
    pass


class HoldoutAlreadyOpened(RegistryError):
    pass


def params_hash(params: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


def register(
    conn: psycopg.Connection,
    *,
    name: str,
    strategy_id: str,
    hypothesis: str,
    style: str,
    param_ranges: Mapping[str, Sequence[float]],
    holdout: tuple[date, date],
    now: datetime,
) -> int:
    if not hypothesis.strip():
        raise RegistryError("a hypothesis is required before any trial")
    for k, r in param_ranges.items():
        if len(r) != 2 or r[0] > r[1]:
            raise RegistryError(f"range for {k!r} must be [low, high] with low <= high")
    row = conn.execute(
        "INSERT INTO experiment (name,strategy_id,hypothesis,style,param_ranges,holdout_start,"
        "holdout_end,registered_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING experiment_id",
        (name, strategy_id, hypothesis, style, Jsonb(param_ranges), *holdout, require_utc(now)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _experiment(conn: psycopg.Connection, exp_id: int) -> tuple[dict[str, Any], date, date]:
    row = conn.execute(
        "SELECT param_ranges, holdout_start, holdout_end FROM experiment WHERE experiment_id=%s",
        (exp_id,),
    ).fetchone()
    if row is None:
        raise RegistryError(f"no experiment {exp_id}")
    return row[0], row[1], row[2]


def record_trial(
    conn: psycopg.Connection,
    exp_id: int,
    params: Mapping[str, Any],
    sharpe: float | None,
    run_id: int | None,
    now: datetime,
) -> int:
    """Count one configuration. Re-running the same params is not a new trial. Returns N."""
    ranges, _, _ = _experiment(conn, exp_id)
    for k, v in params.items():
        if k not in ranges:
            raise RegistryError(f"parameter {k!r} was not pre-registered")
        lo, hi = ranges[k]
        if not lo <= v <= hi:
            raise RegistryError(f"parameter {k!r}={v} is outside the registered range [{lo}, {hi}]")
    conn.execute(
        "INSERT INTO experiment_trial (experiment_id,params,params_hash,sharpe,run_id,recorded_at)"
        " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (experiment_id,params_hash) DO NOTHING",
        (exp_id, Jsonb(params), params_hash(params), sharpe, run_id, require_utc(now)),
    )
    return trial_count(conn, exp_id)


def trial_count(conn: psycopg.Connection, exp_id: int) -> int:
    row = conn.execute(
        "SELECT count(*) FROM experiment_trial WHERE experiment_id=%s", (exp_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def trial_sharpes(conn: psycopg.Connection, exp_id: int) -> list[float]:
    """Per-period Sharpe of every trial with a defined one (the DSR's cross-trial variance)."""
    return [
        float(r[0])
        for r in conn.execute(
            "SELECT sharpe FROM experiment_trial WHERE experiment_id=%s AND sharpe IS NOT NULL"
            " ORDER BY trial_id",
            (exp_id,),
        )
    ]


def assert_research_window(conn: psycopg.Connection, exp_id: int, last_day: date) -> None:
    """Development runs must end before the holdout starts."""
    _, h_start, _ = _experiment(conn, exp_id)
    if last_day >= h_start:
        raise RegistryError(f"run ends {last_day}, inside the holdout that starts {h_start}")


def open_holdout(conn: psycopg.Connection, exp_id: int, run_id: int, now: datetime) -> None:
    """Atomically claim the one-time right to look at the holdout."""
    _experiment(conn, exp_id)
    cur = conn.execute(
        "UPDATE experiment SET holdout_opened_at=%s, holdout_run_id=%s"
        " WHERE experiment_id=%s AND holdout_opened_at IS NULL",
        (require_utc(now), run_id, exp_id),
    )
    if cur.rowcount != 1:
        raise HoldoutAlreadyOpened(f"experiment {exp_id}: the holdout was already opened")


def save_report(
    conn: psycopg.Connection,
    exp_id: int,
    run_id: int,
    report: Report,
    evidence: Evidence,
    n_trials: int,
    now: datetime,
) -> int:
    gates = [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in report.gates]
    row = conn.execute(
        "INSERT INTO validation_report (experiment_id,run_id,passed,thresholds_status,n_trials,"
        "evidence,gates,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING report_id",
        (exp_id, run_id, report.passed, report.thresholds_status, n_trials,
         Jsonb(vars(evidence)), Jsonb(gates), require_utc(now)),
    ).fetchone()  # fmt: skip
    assert row is not None
    return int(row[0])


def validation_passed(conn: psycopg.Connection, run_id: int) -> bool:
    """True only for a passing report made against CONFIRMED (not provisional) thresholds."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM validation_report WHERE run_id=%s AND passed"
        " AND thresholds_status='confirmed')",
        (run_id,),
    ).fetchone()
    assert row is not None
    return bool(row[0])

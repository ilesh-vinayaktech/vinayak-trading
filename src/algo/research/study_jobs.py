# ruff: noqa: E501
"""The queue and the results of a study's runs (migration 046): ask for a run, let a worker claim it, watch its progress,
read the trials. Only one run per study may be active; a worker claims a queued run with SKIP LOCKED so two workers never
take the same one."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

RUN_COLUMNS = [
    "run_id",
    "experiment_id",
    "kind",
    "status",
    "total",
    "done",
    "current",
    "step_done",
    "step_total",
    "cancel_requested",
    "error",
    "detail",
    "requested_by",
    "created_at",
    "started_at",
    "finished_at",
]
TRIAL_COLUMNS = [
    "trial_id",
    "variant",
    "params",
    "params_hash",
    "status",
    "metrics",
    "backtest_run",
    "error",
    "seconds",
    "finished_at",
]


class JobError(ValueError):
    pass


def _run(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    return None if row is None else dict(zip(RUN_COLUMNS, row, strict=True))


def enqueue(
    conn: psycopg.Connection, experiment_id: int, user: UUID, now: datetime, kind: str = "trials"
) -> int:
    if (
        conn.execute(
            "SELECT 1 FROM experiment WHERE experiment_id=%s AND study IS NOT NULL",
            (experiment_id,),
        ).fetchone()
        is None
    ):
        raise JobError("no such study")
    try:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO study_run (experiment_id, kind, status, requested_by, created_at) VALUES (%s,%s,'QUEUED',%s,%s) RETURNING run_id",
                (experiment_id, kind, user, now),
            ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise JobError("this study already has a run queued or running") from e
    assert row is not None
    run_id: int = row[0]
    return run_id


def claim(conn: psycopg.Connection, now: datetime) -> int | None:
    """Take the oldest queued run for this worker (None when there is none)."""
    row = conn.execute(
        "UPDATE study_run SET status='RUNNING', started_at=%s WHERE run_id = ("
        "  SELECT run_id FROM study_run WHERE status='QUEUED' ORDER BY run_id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING run_id",
        (now,),
    ).fetchone()
    return None if row is None else int(row[0])


def get_run(conn: psycopg.Connection, run_id: int) -> dict[str, Any] | None:
    return _run(
        conn.execute(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM study_run WHERE run_id=%s", (run_id,)
        ).fetchone()
    )


def latest_run(
    conn: psycopg.Connection, experiment_id: int, kind: str = "trials"
) -> dict[str, Any] | None:
    return _run(
        conn.execute(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM study_run WHERE experiment_id=%s AND kind=%s ORDER BY run_id DESC LIMIT 1",
            (experiment_id, kind),
        ).fetchone()
    )


def cancel(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    """Stop a job. One that is still waiting is cancelled at once; one that has started is asked to stop, and the worker ends it
    at its next check (within a couple of seconds). Trials already finished are kept."""
    done = conn.execute(
        "UPDATE study_run SET status='CANCELLED', finished_at=%s WHERE run_id=%s AND status='QUEUED'",
        (now, run_id),
    )
    if done.rowcount == 0:
        asked = conn.execute(
            "UPDATE study_run SET cancel_requested=true WHERE run_id=%s AND status='RUNNING'",
            (run_id,),
        )
        if asked.rowcount == 0:
            raise JobError("this run cannot be cancelled: it has already finished")


def stop_requested(conn: psycopg.Connection, run_id: int) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM study_run WHERE run_id=%s", (run_id,)
    ).fetchone()
    return bool(row and row[0])


def start(
    conn: psycopg.Connection,
    run_id: int,
    total: int,
    done: int,
    detail: dict[str, Any],
    now: datetime,
) -> None:
    conn.execute(
        "UPDATE study_run SET status='RUNNING', started_at=COALESCE(started_at, %s), total=%s, done=%s, detail=%s WHERE run_id=%s",
        (now, total, done, Jsonb(detail), run_id),
    )


def progress(conn: psycopg.Connection, run_id: int, done: int, current: str | None) -> None:
    """One unit (a combination, a stress run) finished or started: the day counter inside it starts again."""
    conn.execute(
        "UPDATE study_run SET done=%s, current=%s, step_done=0, step_total=0 WHERE run_id=%s",
        (done, current, run_id),
    )


def day_progress(conn: psycopg.Connection, run_id: int, day: int, of: int) -> None:
    """Days done of the backtest being run now (shown as a bar and used for the time left)."""
    conn.execute(
        "UPDATE study_run SET step_done=%s, step_total=%s WHERE run_id=%s", (day, of, run_id)
    )


def estimate(run: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """How far a running job is and how long it has left, from its own pace so far. None while it is waiting or finished.
    The time left is None until there is enough work done to judge the pace (about 2% of a unit)."""
    if run["status"] != "RUNNING" or run["total"] <= 0 or run["started_at"] is None:
        return None
    frac = min(run["step_done"] / run["step_total"], 1.0) if run["step_total"] else 0.0
    done = min(run["done"] + frac, float(run["total"]))
    elapsed = max((now - run["started_at"]).total_seconds(), 0.0)
    work = done - (run.get("detail") or {}).get(
        "done_at_start", 0
    )  # not the trials a resumed run skipped
    eta = None if work < 0.02 or elapsed <= 0 else round(elapsed / work * (run["total"] - done))
    return {
        "fraction": done / run["total"], "elapsed_seconds": round(elapsed), "eta_seconds": eta,
        "step_done": run["step_done"], "step_total": run["step_total"],
    }  # fmt: skip


def finish(
    conn: psycopg.Connection, run_id: int, status: str, now: datetime, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE study_run SET status=%s, error=%s, current=NULL, finished_at=%s WHERE run_id=%s",
        (status, error, now, run_id),
    )


def done_hashes(conn: psycopg.Connection, experiment_id: int) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT params_hash FROM study_trial WHERE experiment_id=%s AND status='DONE'",
            (experiment_id,),
        )
    }


def save_trial(
    conn: psycopg.Connection, experiment_id: int, params: dict[str, Any], params_hash: str, status: str, now: datetime, *,
    metrics: dict[str, Any] | None = None, returns: list[float] | None = None, backtest_run: int | None = None,
    error: str | None = None, seconds: float | None = None,
) -> None:  # fmt: skip
    """A finished attempt at one combination; a failed attempt is replaced when the combination is tried again."""
    conn.execute(
        "INSERT INTO study_trial (experiment_id, variant, params, params_hash, status, metrics, returns, backtest_run, error, seconds, finished_at)"
        " VALUES (%s,'base',%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (experiment_id, params_hash, variant) DO UPDATE SET status=EXCLUDED.status,"
        " metrics=EXCLUDED.metrics, returns=EXCLUDED.returns, backtest_run=EXCLUDED.backtest_run, error=EXCLUDED.error, seconds=EXCLUDED.seconds, finished_at=EXCLUDED.finished_at",
        (
            experiment_id,
            Jsonb(params),
            params_hash,
            status,
            None if metrics is None else Jsonb(metrics),
            None if returns is None else Jsonb(returns),
            backtest_run,
            error,
            seconds,
            now,
        ),
    )


def trials(conn: psycopg.Connection, experiment_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(TRIAL_COLUMNS)} FROM study_trial WHERE experiment_id=%s ORDER BY params, trial_id",
        (experiment_id,),
    ).fetchall()
    return [dict(zip(TRIAL_COLUMNS, r, strict=True)) for r in rows]


def trial_returns(conn: psycopg.Connection, experiment_id: int) -> dict[str, list[float]]:
    """params_hash -> daily returns, for the trials that finished."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT params_hash, returns FROM study_trial WHERE experiment_id=%s AND status='DONE' ORDER BY trial_id",
            (experiment_id,),
        )
    }


def latest_report(conn: psycopg.Connection, experiment_id: int) -> dict[str, Any] | None:
    """The newest pass/fail verdict made for this study, with every gate and the evidence behind it."""
    row = conn.execute(
        "SELECT report_id, run_id, passed, thresholds_status, n_trials, evidence, gates, refs, created_at"
        " FROM validation_report WHERE experiment_id=%s ORDER BY report_id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if row is None:
        return None
    keys = (
        "report_id",
        "run_id",
        "passed",
        "thresholds_status",
        "n_trials",
        "evidence",
        "gates",
        "refs",
        "created_at",
    )
    return dict(zip(keys, row, strict=True))


def trials_finished(conn: psycopg.Connection, experiment_id: int) -> tuple[int, int]:
    """(finished, planned) combinations of the study."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM study_trial WHERE experiment_id=%s AND status='DONE'),"
        " jsonb_array_length(study->'combinations') FROM experiment WHERE experiment_id=%s",
        (experiment_id, experiment_id),
    ).fetchone()
    if row is None:
        raise JobError("no such study")
    return int(row[0]), int(row[1])


def holdout_result(conn: psycopg.Connection, experiment_id: int) -> dict[str, Any] | None:
    """The one-time holdout test of this study, once it has been opened."""
    row = conn.execute(
        "SELECT run_id, passed, evidence, gates, refs, created_at FROM study_holdout WHERE experiment_id=%s",
        (experiment_id,),
    ).fetchone()
    keys = ("run_id", "passed", "evidence", "gates", "refs", "created_at")
    return None if row is None else dict(zip(keys, row, strict=True))

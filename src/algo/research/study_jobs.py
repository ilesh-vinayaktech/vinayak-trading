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
    "status",
    "total",
    "done",
    "current",
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


def enqueue(conn: psycopg.Connection, experiment_id: int, user: UUID, now: datetime) -> int:
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
                "INSERT INTO study_run (experiment_id, status, requested_by, created_at) VALUES (%s,'QUEUED',%s,%s) RETURNING run_id",
                (experiment_id, user, now),
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


def latest_run(conn: psycopg.Connection, experiment_id: int) -> dict[str, Any] | None:
    return _run(
        conn.execute(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM study_run WHERE experiment_id=%s ORDER BY run_id DESC LIMIT 1",
            (experiment_id,),
        ).fetchone()
    )


def cancel(conn: psycopg.Connection, run_id: int, now: datetime) -> None:
    done = conn.execute(
        "UPDATE study_run SET status='CANCELLED', finished_at=%s WHERE run_id=%s AND status='QUEUED'",
        (now, run_id),
    )
    if done.rowcount == 0:
        raise JobError("this run cannot be cancelled: it has started or finished")


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
    conn.execute(
        "UPDATE study_run SET done=%s, current=%s WHERE run_id=%s", (done, current, run_id)
    )


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

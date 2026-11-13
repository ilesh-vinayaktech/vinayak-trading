"""The record of scheduled job runs: written by the runner, read by the portal ("last sync")."""

from __future__ import annotations

from typing import Any

import psycopg

from algo.jobs.registry import JOBS
from algo.jobs.runner import JobRun

KEEP = 200  # runs kept per job: months of history for a daily job, and the table stays small


def record(conn: psycopg.Connection, run: JobRun) -> None:
    conn.execute(
        "INSERT INTO job_run (job, started_at, finished_at, status, attempts, detail)"
        " VALUES (%s,%s,%s,%s,%s,%s)",
        (run.job, run.started_at, run.finished_at, run.status, run.attempts, run.detail),
    )
    conn.execute(
        "DELETE FROM job_run WHERE job=%s AND run_id NOT IN"
        " (SELECT run_id FROM job_run WHERE job=%s ORDER BY started_at DESC, run_id DESC LIMIT %s)",
        (run.job, run.job, KEEP),
    )


def status(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Every registered job, in registry order, with its latest run and its latest success (None
    when it has never run or never succeeded). Runs of a job no longer registered are not listed."""
    latest = {
        r[0]: r
        for r in conn.execute(
            "SELECT DISTINCT ON (job) job, started_at, finished_at, status, attempts, detail"
            " FROM job_run ORDER BY job, started_at DESC, run_id DESC"
        )
    }
    ok: dict[str, Any] = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT job, max(finished_at) FROM job_run WHERE status='ok' GROUP BY job"
        )
    }
    out = []
    for j in JOBS:
        r = latest.get(j.name)
        out.append(
            {
                "name": j.name,
                "description": j.description,
                "calendar": j.calendar,
                "last_run": None
                if r is None
                else {
                    "started_at": r[1].isoformat(),
                    "finished_at": r[2].isoformat(),
                    "status": r[3],
                    "attempts": r[4],
                    "detail": r[5],
                },
                "last_success_at": ok[j.name].isoformat() if j.name in ok else None,
            }
        )
    return out

# ruff: noqa: E501
"""Live progress of a long job, written to job_progress (migration 083) so the console can show what is happening while it runs.

Callers: scripts/validate_features.py, compute_features.py, discover_alpha.py; read by `GET /api/intel/progress` and tests/integration/jobs/test_progress.py.
User's instruction: "can we show real time feature validation progress in page as well, so anytime, I know what's going on?"
Use it on its OWN autocommit connection, so each update is visible at once and never waits on the job's own transaction. Time comes from the injected Clock.
`with Progress(...) as p:` starts the run and always finishes it: DONE when the block ends, FAILED (with the error) when it raises. A job that is killed cannot finish
its own row, so `reap` marks RUNNING rows whose process is gone as FAILED. Progress is for people to watch: nothing decides anything from it."""

from __future__ import annotations

import os
from collections.abc import Callable
from types import TracebackType
from typing import Any

import psycopg

from algo.core.clock import Clock

KEEP_DAYS = 30


class Progress:
    def __init__(
        self,
        conn: psycopg.Connection,
        clock: Clock,
        job: str,
        label: str,
        total: int,
        *,
        pid: int | None = None,
        uniform: bool = True,
    ) -> None:
        if total < 1:
            raise ValueError("a job has at least one step")
        self.conn, self.clock, self.job, self.label, self.total = conn, clock, job, label, total
        self.pid = os.getpid() if pid is None else pid
        self.uniform = (
            uniform  # False when the steps differ a lot in size, so no time estimate is offered
        )
        self.run_id: int | None = None

    def start(self, phase: str = "starting") -> int:
        now = self.clock.now()
        self.conn.execute(
            "DELETE FROM job_progress WHERE status <> 'RUNNING' AND finished_at < %s - make_interval(days => %s)",
            (now, KEEP_DAYS),
        )
        row = self.conn.execute(
            "INSERT INTO job_progress (job, label, pid, status, done, total, phase, started_at, updated_at, uniform) VALUES (%s,%s,%s,'RUNNING',0,%s,%s,%s,%s,%s) RETURNING run_id",
            (self.job, self.label, self.pid, self.total, phase, now, now, self.uniform),
        ).fetchone()
        assert row is not None
        self.run_id = int(row[0])
        return self.run_id

    def step(
        self, phase: str, message: str = "", *, done: int | None = None, total: int | None = None
    ) -> None:
        """Say what the job is doing now. `done` (when given) is how many steps are complete; `total` (when given) replaces the step count, for a job that
        only learns it after starting."""
        if self.run_id is None:
            raise RuntimeError("the run has not started")
        if total is not None and total < 1:
            raise ValueError("a job has at least one step")
        limit = self.total if total is None else total
        if done is not None and not 0 <= done <= limit:
            raise ValueError(f"done {done} is outside 0..{limit}")
        now = self.clock.now()
        # the right-hand sides see the OLD row, so `done` below is the count before this update
        self.conn.execute(
            "UPDATE job_progress SET phase=%s, message=%s, total=%s, updated_at=%s,"
            " first_done_at = CASE WHEN first_done_at IS NULL AND %s::int > 0 THEN %s ELSE first_done_at END,"
            " last_done_at = CASE WHEN %s::int > done THEN %s ELSE last_done_at END,"
            " done = coalesce(%s::int, done) WHERE run_id=%s AND status='RUNNING'",
            (phase, message[:500], limit, now, done, now, done, now, done, self.run_id),
        )
        self.total = limit

    def finish(self, ok: bool, message: str = "") -> None:
        if self.run_id is None:
            raise RuntimeError("the run has not started")
        now = self.clock.now()
        self.conn.execute(
            "UPDATE job_progress SET status=%s, done=CASE WHEN %s THEN total ELSE done END, phase=%s, message=%s, updated_at=%s, finished_at=%s WHERE run_id=%s AND status='RUNNING'",
            (
                "DONE" if ok else "FAILED",
                ok,
                "finished" if ok else "failed",
                message[:500],
                now,
                now,
                self.run_id,
            ),
        )

    def __enter__(self) -> Progress:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is None:
            self.finish(True)
        else:
            self.finish(False, f"{exc_type.__name__ if exc_type else 'error'}: {exc}")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, just not ours
    return True


def reap(conn: psycopg.Connection, clock: Clock, *, is_alive: Callable[[int], bool] = alive) -> int:
    """Mark RUNNING rows whose process has gone as FAILED; returns how many."""
    n = 0
    for run_id, pid in conn.execute(
        "SELECT run_id, pid FROM job_progress WHERE status='RUNNING'"
    ).fetchall():
        if not is_alive(pid):
            now = clock.now()
            conn.execute(
                "UPDATE job_progress SET status='FAILED', phase='failed', message='the process ended without finishing', updated_at=%s, finished_at=%s WHERE run_id=%s AND status='RUNNING'",
                (now, now, run_id),
            )
            n += 1
    return n


def recent(conn: psycopg.Connection, limit: int = 10) -> list[dict[str, Any]]:
    cols = (
        "run_id",
        "job",
        "label",
        "pid",
        "status",
        "done",
        "total",
        "phase",
        "message",
        "started_at",
        "updated_at",
        "finished_at",
        "first_done_at",
        "last_done_at",
        "first_done_count",
        "uniform",
    )
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM job_progress ORDER BY (status = 'RUNNING') DESC, started_at DESC LIMIT %s",
        (limit,),
    ).fetchall()  # noqa: S608 - fixed column list
    return [dict(zip(cols, r, strict=True)) for r in rows]

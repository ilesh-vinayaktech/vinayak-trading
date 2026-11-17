"""The record of scheduled job runs: what ran, when, and how it ended (portal: "last sync")."""

from datetime import UTC, datetime, timedelta

import pytest

from algo.data.store.migrate import migrate
from algo.jobs import history
from algo.jobs.registry import JOBS
from algo.jobs.runner import JobRun

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)


def run(job, status, minutes, detail="", attempts=1):
    start = T0 + timedelta(minutes=minutes)
    return JobRun(job, start, start + timedelta(seconds=30), status, attempts, detail)


def test_every_registered_job_is_listed_even_when_it_has_never_run(conn):
    migrate(conn)
    rows = history.status(conn)
    assert [r["name"] for r in rows] == [j.name for j in JOBS]
    assert all(r["last_run"] is None and r["last_success_at"] is None for r in rows)
    first = rows[0]
    assert first["description"] == JOBS[0].description and first["calendar"] == JOBS[0].calendar


def test_the_latest_run_and_the_latest_success_are_kept_apart(conn):
    migrate(conn)
    name = JOBS[1].name
    history.record(conn, run(name, "ok", 0))
    history.record(conn, run(name, "failed", 60, "a.py exited 3", attempts=3))
    history.record(conn, run("not-a-registered-job", "ok", 5))  # ignored: not one of ours
    row = next(r for r in history.status(conn) if r["name"] == name)
    assert row["last_run"] == {
        "started_at": "2026-11-13T14:00:00+00:00",
        "finished_at": "2026-11-13T14:00:30+00:00",
        "status": "failed",
        "attempts": 3,
        "detail": "a.py exited 3",
    }
    assert row["last_success_at"] == "2026-11-13T13:00:30+00:00"  # the earlier ok run
    assert len(history.status(conn)) == len(JOBS)


def test_old_runs_are_trimmed_so_the_table_stays_small(conn):
    migrate(conn)
    name = JOBS[0].name
    for i in range(history.KEEP + 5):
        history.record(conn, run(name, "ok", i))
    (n,) = conn.execute("SELECT count(*) FROM job_run WHERE job=%s", (name,)).fetchone()
    assert n == history.KEEP
    row = next(r for r in history.status(conn) if r["name"] == name)
    assert row["last_run"]["started_at"] == (T0 + timedelta(minutes=history.KEEP + 4)).isoformat()


def test_the_last_success_is_when_the_latest_ok_run_started_and_failures_do_not_count(conn):
    migrate(conn)
    name = JOBS[1].name
    assert history.last_success(conn, name) is None
    history.record(conn, run(name, "failed", 0, "x"))
    assert history.last_success(conn, name) is None  # only failures: never succeeded
    history.record(conn, run(name, "ok", 10))
    history.record(conn, run(name, "skipped", 20, "no session"))
    history.record(conn, run(name, "failed", 30, "x"))
    assert history.last_success(conn, name) == T0 + timedelta(minutes=10)
    assert history.last_success(conn, JOBS[2].name) is None  # another job's runs do not count

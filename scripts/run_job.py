# ruff: noqa: E501
"""Run one scheduled job (lock, log, retries, alert). usage: run_job.py NAME | --list
Alerts go to Telegram when ALGO_TELEGRAM_TOKEN and ALGO_TELEGRAM_CHAT are set, else to the journal."""

import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from algo.core.clock import SystemClock
from algo.jobs import history
from algo.jobs.registry import JOBS
from algo.jobs.runner import JobRun, run_job, telegram_alert
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed_credentials

by_name = {j.name: j for j in JOBS}
if len(sys.argv) != 2 or sys.argv[1] not in {*by_name, "--list"}:
    sys.exit(f"usage: run_job.py {' | '.join(by_name)} | --list")
if sys.argv[1] == "--list":
    for j in JOBS:
        print(f"{j.name:22} {j.calendar:38} {j.description}")
    sys.exit(0)


def record(run: JobRun) -> None:
    """Keep how the run ended, for the portal. Needs ALGO_DB_URL; without it the run is only logged."""
    url = os.environ.get("ALGO_DB_URL")
    if url:
        with psycopg.connect(url, autocommit=True) as conn:
            history.record(conn, run)


def session_ok(now) -> bool:
    """A valid Kite session also exists when the portal's data feed is connected (the loaders use it)."""
    url = os.environ.get("ALGO_DB_URL")
    if not url:
        return False
    with psycopg.connect(url) as conn:
        return system_feed_credentials(conn, KeyRing.from_env(os.environ), now=now) is not None


def last_success(name: str) -> datetime | None:
    """When this job last succeeded, so a run after missed days covers them; unknown (no database, or it cannot be read) means the plain windows."""
    url = os.environ.get("ALGO_DB_URL")
    if not url:
        return None
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            return history.last_success(conn, name)
    except psycopg.Error:
        return None


sys.exit(
    run_job(
        by_name[sys.argv[1]],
        clock=SystemClock(),
        alert=telegram_alert(os.environ),
        lock_dir=Path("data/locks"),
        log_dir=Path("data/logs"),
        record=record,
        session_ok=session_ok,
        last_success=last_success,
    )
)

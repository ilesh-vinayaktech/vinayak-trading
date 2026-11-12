# ruff: noqa: E501  (driver script)
"""Run queued backtest studies. Polls the queue (study_run) and executes each claimed run to the end, one at a time.

A run can take hours (every parameter combination is a full backtest), so this is its own long-running process, not part of
the web server: start it and leave it running. Run exactly ONE worker: on start it puts back in the queue any run a worker that
died left RUNNING (trials already done are kept and skipped, the rest are run), which a second live worker would also do.
usage: study_worker.py [--db URL] [--once] [--interval 5]
  --once   process what is queued now, then exit"""

import argparse
import os
import signal
import sys
import time
from datetime import UTC, datetime

import psycopg

from algo.research import study_jobs
from algo.research.study_runner import run_study

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--once", action="store_true")
ap.add_argument("--interval", type=float, default=5.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

stop = False


def _stop(*_: object) -> None:
    global stop
    stop = True
    print("stopping once the current run finishes", flush=True)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

with psycopg.connect(a.db, autocommit=True) as conn:
    conn.execute("UPDATE study_run SET status='QUEUED' WHERE status='RUNNING'")
    while not stop:
        run_id = study_jobs.claim(conn, datetime.now(UTC))
        if run_id is None:
            if a.once:
                break
            time.sleep(a.interval)
            continue
        print(f"{datetime.now(UTC):%H:%M:%S} run {run_id}: started", flush=True)
        run_study(conn, run_id, datetime.now(UTC))
        run = study_jobs.get_run(conn, run_id)
        print(
            f"{datetime.now(UTC):%H:%M:%S} run {run_id}: {run['status'] if run else '?'} {(run or {}).get('error') or ''}",
            flush=True,
        )

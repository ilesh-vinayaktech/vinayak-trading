# ruff: noqa: E501  (driver script)
"""Run queued backtest studies. Polls the queue (study_run) and executes each claimed run to the end, one at a time.

A run can take hours (every parameter combination is a full backtest), so this is its own long-running process, not part of
the web server: start it and leave it running. Start as many workers as you want to run studies side by side (each is about 2 GB
of memory): every worker takes its own run, and different studies run in parallel (one study never runs twice at once). On start
a worker puts back in the queue any run whose worker died and left it RUNNING (trials already done are kept and skipped, the
rest are run); a run another live worker is on is left alone.
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
from algo.research.study_runner import execute

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
    study_jobs.requeue_orphans(conn)
    while not stop:
        run_id = study_jobs.claim(conn, datetime.now(UTC))
        if run_id is None:
            if a.once:
                break
            time.sleep(a.interval)
            continue
        print(f"{datetime.now(UTC):%H:%M:%S} run {run_id}: started", flush=True)
        try:
            execute(conn, run_id, datetime.now(UTC))
        finally:
            study_jobs.release(conn, run_id)
        run = study_jobs.get_run(conn, run_id)
        print(
            f"{datetime.now(UTC):%H:%M:%S} run {run_id}: {run['status'] if run else '?'} {(run or {}).get('error') or ''}",
            flush=True,
        )

# ruff: noqa: E501  (driver script)
"""Run queued backtest studies. Polls the queue (study_run) and executes each claimed run to the end, one at a time.

A run can take hours (every parameter combination is a full backtest), so this is its own long-running process, not part of
the web server: start it and leave it running. Workers may be started side by side, but every run holds the one research slot (algo.research.slot) while it executes, so runs take turns:
only one research job runs on the machine at a time (a waiting worker has claimed its run and says so in its heartbeat; one study never runs twice at once). On start
a worker puts back in the queue any run whose worker died and left it RUNNING (trials already done are kept and skipped, the
rest are run); a run another live worker is on is left alone.
usage: study_worker.py [--db URL] [--once] [--interval 5]
  --once   process what is queued now, then exit"""

import argparse
import os
import signal
import socket
import sys
import threading
import time
from datetime import UTC, datetime

import psycopg

from algo.live import heartbeat
from algo.research import slot, study_jobs
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

doing = "idle"  # what the heartbeat thread reports
beating = threading.Event()


def _heartbeats() -> None:
    """Its own connection and thread: a study can run for an hour, and the worker must not look silent meanwhile."""
    with psycopg.connect(a.db, autocommit=True) as hb:
        while not beating.is_set():
            heartbeat.beat(
                hb,
                "study_worker",
                "RUNNING",
                doing,
                datetime.now(UTC),
                pid=os.getpid(),
                host=socket.gethostname(),
            )
            beating.wait(30)
        heartbeat.beat(
            hb,
            "study_worker",
            "STOPPED",
            "stopped",
            datetime.now(UTC),
            pid=os.getpid(),
            host=socket.gethostname(),
        )


with psycopg.connect(a.db, autocommit=True) as conn:
    heartbeat.beat(
        conn,
        "study_worker",
        "STARTING",
        "starting",
        datetime.now(UTC),
        pid=os.getpid(),
        host=socket.gethostname(),
    )
    thread = threading.Thread(target=_heartbeats, daemon=True)
    thread.start()
    study_jobs.requeue_orphans(conn)

    while not stop:
        run_id = study_jobs.claim(conn, datetime.now(UTC))
        if run_id is None:
            doing = "idle"
            if a.once:
                break
            time.sleep(a.interval)
            continue
        doing = f"run {run_id}"
        print(f"{datetime.now(UTC):%H:%M:%S} run {run_id}: started", flush=True)
        try:
            doing = f"run {run_id} (waiting for the research slot)"
            with slot.hold(
                conn, f"study run {run_id}", nice=10
            ):  # one research job at a time on this machine
                doing = f"run {run_id}"
                execute(conn, run_id, datetime.now(UTC))
        finally:
            study_jobs.release(conn, run_id)
        run = study_jobs.get_run(conn, run_id)
        print(
            f"{datetime.now(UTC):%H:%M:%S} run {run_id}: {run['status'] if run else '?'} {(run or {}).get('error') or ''}",
            flush=True,
        )
    beating.set()
    thread.join(timeout=5)

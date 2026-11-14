# ruff: noqa: E501
"""Decide for every enabled paper account on the newest session (run after the evening data jobs). Exit 1 when there is no session to decide
on (the data is not current), or an account's run ended in ERROR (data not ready, strategy failed or halted); SKIPPED accounts (switched off,
paused, kill switch) are normal. Safe to repeat: a day already proposed returns the same proposals.
usage: run_paper.py [--db URL] [--lake data/lake] [--sandbox]"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.paper import jobs
from algo.paper.runner import SandboxConfig

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument(
    "--sandbox", action="store_true", help="run each strategy in a sandboxed worker process"
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    day = jobs.decision_day(conn, now)
    if day is None:
        sys.exit("no session to decide on: the newest bars are not the latest published session")
    results = jobs.run_accounts(
        conn, now, lake_root=a.lake, day=day, sandbox=SandboxConfig() if a.sandbox else None
    )
print(f"decision day {day}: {len(results)} account(s)")
bad = 0
for user, out in results:
    note = out.detail.get("reason", "")
    print(f"  {user} {out.status} {len(out.orders)} order(s) {note}")
    bad += out.status == "ERROR"
sys.exit(1 if bad else 0)

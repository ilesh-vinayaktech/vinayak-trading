# ruff: noqa: E501
"""Alert when the live and news data has stopped arriving (algo/jobs/data_checks.py): index quotes and minute bars, the news feed, headlines waiting for the Laya model, the live market
zone's baseline, and the index constituent lists. Exit 1 with one line per problem, so the job runner alerts. usage: check_live_data.py [--db URL] [--lake DIR]"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.jobs import data_checks

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    found = data_checks.problems(conn, datetime.now(UTC), a.lake)
for p in found:
    print(f"[{p.level}] {p.text}")
print(f"{len(found)} problem(s)")
sys.exit(1 if found else 0)

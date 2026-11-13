# ruff: noqa: E501
"""Exit 1 if the newest daily bar is behind the latest session whose file should be published (see algo.api.freshness).
usage: check_stale.py [--db URL]  (a step of the scheduled data jobs: the job fails, and alerts, when data is stale)"""

import argparse
import os
import sys
from datetime import date

import psycopg

from algo.api import freshness, queries
from algo.core.clock import SystemClock

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    last = queries.data_health(conn)["last_date"]
    if last is None:
        sys.exit("no daily bars at all")
    r = freshness.assess(
        date.fromisoformat(last), SystemClock().now(), queries.known_holidays(conn)
    )
print(r)
sys.exit(0 if r["status"] == "CURRENT" else 1)

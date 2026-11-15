# ruff: noqa: E501
"""Alert when a process that should be running has gone quiet (docs: TODO 5.3). Reads the heartbeats (the live feed's own status row and
the `process_heartbeat` table); which processes are expected comes from ALGO_EXPECT_PROCESSES (default: the feed, during the session).
Exit 1 with one line per problem, so the job runner alerts. usage: check_heartbeats.py [--db URL]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.live import heartbeat

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
expected = heartbeat.expected_from_env(os.environ)
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    problems = heartbeat.check(conn, datetime.now(UTC), expected)
for p in problems:
    print(p)
print(f"{len(problems)} problem(s) among {len(expected)} expected process(es)")
sys.exit(1 if problems else 0)

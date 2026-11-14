# ruff: noqa: E501
"""Expire what has run out of time and fill approved paper orders at the next live open (run every few minutes while the market is open).
Safe to repeat. Orders still waiting for a live price are left for the next run.
usage: paper_orders.py [--db URL]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.paper import jobs

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    r = jobs.process_orders(conn, datetime.now(UTC))
print(f"filled {r.filled}, failed {r.failed}, waiting for a price {r.waiting}")

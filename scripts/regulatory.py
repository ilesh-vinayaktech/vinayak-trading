# ruff: noqa: E501
"""The regulatory rules live trading depends on (order-rate limit, order types and market protection, tagging, static IP).
  regulatory.py status                      what is recorded and what blocks live; exit 1 when anything blocks it
  regulatory.py record TOPIC --value JSON --source "NSE circular ..." --effective YYYY-MM-DD --by NAME [--verified YYYY-MM-DD]
A re-check is the same command with the same value and today's date. Read the rule yourself first: nothing here fetches or guesses it.
usage: regulatory.py [--db URL] status | record ..."""

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime

import psycopg

from algo.execution import regulatory as reg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("status")
r = sub.add_parser("record")
r.add_argument("topic", choices=reg.REQUIRED)
r.add_argument("--value", required=True, help="JSON: the rule as you read it")
r.add_argument("--source", required=True)
r.add_argument("--effective", type=date.fromisoformat, required=True)
r.add_argument("--by", required=True)
r.add_argument("--verified", type=date.fromisoformat, default=None)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
today = datetime.now(UTC).date()
with psycopg.connect(a.db, autocommit=True) as conn:
    if a.cmd == "record":
        reg.record(
            conn,
            reg.Item(
                reg.EXCHANGE,
                reg.SEGMENT,
                a.topic,
                json.loads(a.value),
                a.effective,
                a.source,
                a.verified or today,
                a.by,
            ),
        )
        print(f"recorded {a.topic}")
    found = reg.in_force(conn)
    blocked = reg.problems(found, today)
for i in found:
    print(
        f"  {i.exchange} {i.segment} {i.topic}: verified {i.last_verified} by {i.verified_by}, from {i.effective_from}, {i.source}"
    )
for m in blocked:
    print(f"  BLOCKS LIVE: {m}")
print("live is blocked" if blocked else "all regulatory rules are recorded and recent")
sys.exit(1 if blocked else 0)

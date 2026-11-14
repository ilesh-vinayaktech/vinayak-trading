# ruff: noqa: E501
"""Exit 1 if the daily NSE bars are incomplete: a quarantined file, an open weekday with no bars that is not a
recorded holiday, or a session with under 90% of the usual number of bars (see algo.data.quality.completeness).
usage: check_completeness.py [--db URL] [--days 30]   (a step of the scheduled data jobs; the job alerts on exit 1)"""

import argparse
import os
import sys
from datetime import timedelta

import psycopg

from algo.core.clock import SystemClock
from algo.data.quality.completeness import check
from algo.live.market_calendar import IST

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--days", type=int, default=30, help="calendar days to look back")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
since = SystemClock().now().astimezone(IST).date() - timedelta(days=a.days)
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    r = check(conn, since)
print(
    f"since {since}: {len(r.quarantined)} quarantined file(s), {len(r.missing_days)} missing day(s), {len(r.thin_days)} thin day(s)"
)
for d in r.quarantined:
    print(f"  QUARANTINED {d}: recover it (scripts/recover_bhavcopy.py), a person decides")
for d in r.missing_days:
    print(f"  MISSING     {d}: no NSE bars and no holiday record (run the gap refill)")
for d, n, avg in r.thin_days:
    print(f"  THIN        {d}: {n} bars against an average of {avg}")
sys.exit(1 if (r.quarantined or r.missing_days or r.thin_days) else 0)

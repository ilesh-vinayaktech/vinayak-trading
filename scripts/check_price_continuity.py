# ruff: noqa: E501
"""Exit 1 if a raw NSE close of the newest session (or of the last N calendar days) jumped (more than 20%) with no corporate action recorded for
that bar, or a recorded split/bonus the price did not follow. Jumps that sit on an action waiting for a person
(review status) or on a dividend/buy-back are printed but do not fail the job.
usage: check_price_continuity.py [--db URL] [--days N] [--record]   (a step of the scheduled data jobs; the job alerts on exit 1)"""

import argparse
import os
import sys
from datetime import timedelta

import psycopg

from algo.core.clock import SystemClock
from algo.data.quality import results
from algo.data.quality.continuity_scan import scan
from algo.live.market_calendar import IST

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--days",
    type=int,
    default=None,
    help="look back N calendar days instead of just the newest session",
)
ap.add_argument("--record", action="store_true", help="store the result in dq_result")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    if a.days is not None:
        since = SystemClock().now().astimezone(IST).date() - timedelta(days=a.days)
    else:  # one alert per jump: only the newest session's bars are new
        row = conn.execute(
            "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
        ).fetchone()
        if row is None or row[0] is None:
            sys.exit("no NSE daily bars at all")
        since = row[0]
    r = scan(conn, since)
if a.record:
    with psycopg.connect(a.db, autocommit=True) as w:
        results.record_continuity(w, r, since, SystemClock().now())
print(
    f"scanned {r.scanned} stocks since {since}: {len(r.unexplained)} unexplained, {len(r.pending)} on a pending action"
)
for f in r.pending:
    print(f"  pending     {f.symbol} {f.day} {f.kind}: {f.detail}")
for f in r.unexplained:
    print(f"  UNEXPLAINED {f.symbol} {f.day} {f.kind}: {f.detail}")
sys.exit(1 if r.unexplained else 0)

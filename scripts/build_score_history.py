# ruff: noqa: E501
"""Build the point-in-time swing score history (TODO 6.2a): the score of every liquid stock as it stood on each day, from what was known then.
usage: build_score_history.py [--db URL] [--all | --since YYYY-MM-DD] [--daily]
`--all` backfills weekly (last trading day of each week) from 2019, one year at a time (first run, tens of minutes). It cannot start earlier: the NSE bars, which carry delivery %
and are the live table's source, begin in October 2019 (the Kite bars before that are vendor-adjusted and have no delivery, so mixing them would change what the score means). `--since` does the same from a date.
Without either it stores the newest trading day (the nightly step). `--daily` stores every trading day instead of one per week. Safe to repeat."""

import argparse
import os
import sys
from datetime import UTC, date, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.screener import history

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--all", action="store_true", help="backfill from 2019")
ap.add_argument("--since", type=date.fromisoformat)
ap.add_argument("--daily", action="store_true", help="every trading day, not one per week")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
today = datetime.now(UTC).date()
since = date(2019, 1, 1) if a.all else a.since
total = 0
with psycopg.connect(a.db) as conn:
    migrate(conn)
    if since is None:
        newest = conn.execute(
            "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
        ).fetchone()
        days = [newest[0]] if newest and newest[0] else []
        total += history.store(conn, history.build(conn, days))
        conn.commit()
    else:
        for year in range(since.year, today.year + 1):
            lo, hi = max(since, date(year, 1, 1)), min(today, date(year, 12, 31))
            if a.daily:
                days = [
                    r[0]
                    for r in conn.execute(
                        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date d FROM bar_1d WHERE source='nse' AND ts >= %s AND ts < %s::date + 1 ORDER BY 1",
                        (lo, hi),
                    )
                ]
            else:
                days = history.week_ends(conn, lo, hi)
            n = history.store(conn, history.build(conn, days))
            conn.commit()
            total += n
            print(f"  {year}: {len(days)} days, {n} scores", flush=True)
    span = conn.execute(
        "SELECT min(day), max(day), count(DISTINCT day), count(*) FROM stock_score_history"
    ).fetchone()
print(f"score history: {total} scores written; table now {span}")

# ruff: noqa: E501
"""FII index-futures open interest from NSE's daily participant-wise OI file into fii_index_futures_oi. Weekends and holidays have no file and are skipped.
usage: ingest_participant_oi.py [--db URL] [--from YYYY-MM-DD] [--to YYYY-MM-DD]   (default the last 10 days; `--from 2016-01-01` backfills, about 2,700 requests
at NSE's polite pace, and resumes where it stopped). Safe to repeat."""

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta

import psycopg

from algo.data import participant_oi as p
from algo.data.providers.nse_client import NotPublished, NseClient, NseHttpError

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", type=date.fromisoformat)
ap.add_argument("--to", dest="end", type=date.fromisoformat)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
end = a.end or now.date()
start = a.start or end - timedelta(days=10)
client = NseClient()
client.warm(p.WARM)
new = skipped = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    have = p.stored_days(conn, start, end)
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in have:
            try:
                day, long_oi, short_oi = p.parse(
                    client.get(p.URL.format(day=d), accept="text/csv,*/*"), d
                )
            except NotPublished:
                skipped += 1  # a holiday, or today's file not out yet
            except NseHttpError as e:
                sys.exit(f"NSE refused {d}: HTTP {e.status}; re-run later (resumes)")
            else:
                new += p.store(conn, day, long_oi, short_oi, now)
                if new % 100 == 0:
                    print(f"  {new} days stored (at {d})", flush=True)
        d += timedelta(days=1)
print(f"participant OI: {new} new days, {skipped} with no file ({start} to {end})")

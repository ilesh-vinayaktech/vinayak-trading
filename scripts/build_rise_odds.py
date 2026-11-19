# ruff: noqa: E501
"""Score every liquid stock's rise odds for the newest trading day(s) (algo.market.rise_odds), training a new model first when there is none or it is over six weeks old.
usage: build_rise_odds.py [--db URL] [--backfill-from YYYY-MM-DD]
Run nightly after the day's bars are loaded (part of the `market-zone` job). `--backfill-from` makes the history instead, walk-forward: for each year from that date a model trained only
on the data before it scores that year (a one-off; several minutes). Exit 1 when nothing could be scored for lack of bars or history (the job runner alerts); 0 otherwise."""

import argparse
import os
import sys
from datetime import UTC, date, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.market import rise_odds

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--backfill-from",
    type=date.fromisoformat,
    help="make the walk-forward history from this date instead of the nightly run",
)
ap.add_argument(
    "--kind",
    choices=sorted(rise_odds.KINDS),
    help="with --backfill-from: only this kind (rel = against the other stocks, up = own direction)",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db) as conn:
    migrate(conn)
    if a.backfill_from:
        n = rise_odds.backfill(conn, a.backfill_from, now, kinds=(a.kind,) if a.kind else None)
        conn.commit()
        print(f"rise odds: {n} walk-forward scores stored from {a.backfill_from}")
        sys.exit(0 if n else 1)
    out = rise_odds.nightly(conn, now)
    conn.commit()
print(f"rise odds: {out.status}: {out.detail}")
sys.exit(1 if out.status in ("no_bars", "too_little_history") else 0)

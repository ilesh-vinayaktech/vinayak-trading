# ruff: noqa: E501
"""Score the hold signal (algo.market.hold_signal): the BUY / HOLD / SELL call of the frozen rule for every liquid stock on every bar day not scored yet, training the year's model first when it is missing.
usage: build_hold_signal.py [--db URL] [--backfill-from YYYY-MM-DD]
Run nightly after the day's bars are loaded (part of the `market-zone` job). The first run makes the whole history from 2022-01-01 (a few minutes: it trains one model per year). `--backfill-from` drops the stored
signals from that day on and makes them again, one unbroken walk-forward run. Exit 1 when nothing could be scored for lack of bars or history (the job runner alerts); 0 otherwise."""

import argparse
import os
import sys
from datetime import UTC, date, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.market import hold_signal

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--backfill-from",
    type=date.fromisoformat,
    help="drop the stored signals from this day on and make them again",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
with psycopg.connect(a.db) as conn:
    migrate(conn)
    if a.backfill_from:
        out = hold_signal.backfill(conn, a.backfill_from, now, progress=print)
    else:
        out = hold_signal.nightly(conn, now, progress=print)
    conn.commit()
print(f"hold signal: {out.status}: {out.detail}")
sys.exit(1 if out.status in ("no_bars", "too_little_history") else 0)

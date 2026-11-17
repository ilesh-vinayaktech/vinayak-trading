# ruff: noqa: E501
"""Build the market zone table: breadth from every liquid stock's daily bar, then the fear/greed score and the bull/bear and calm/stressed regime for each day.
usage: build_market_zone.py [--db URL] [--all | --since YYYY-MM-DD]
The daily job runs it for the last ten days (the ranking reads all stored history, so earlier days are unchanged). `--all` rebuilds from the start of
history (first run, a few minutes). Safe to repeat. A step of the market-zone job, after the screener refresh."""

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta

import psycopg

from algo.data.store.migrate import migrate
from algo.market.build import refresh, refresh_breadth, score

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--all", action="store_true", help="rebuild from the start of history")
ap.add_argument("--since", type=date.fromisoformat)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
since = date(2016, 1, 1) if a.all else a.since or (now.date() - timedelta(days=10))
with psycopg.connect(a.db) as conn:
    migrate(conn)
    if a.all:  # one year at a time: the first run would otherwise window over every bar at once
        stored = 0
        for year in range(since.year, now.year + 1):
            stored += refresh_breadth(conn, date(year, 1, 1), now, date(year, 12, 31))
            conn.commit()
            print(f"  breadth {year}: done", flush=True)
        scored = score(conn, since, now)
    else:
        stored, scored = refresh(conn, since, now)
    conn.commit()
    last = conn.execute(
        "SELECT day, fear_greed, label, trend, volatility, advancers, decliners FROM market_regime_daily ORDER BY day DESC LIMIT 1"
    ).fetchone()
print(f"market zone: {stored} days of breadth stored, {scored} days scored (since {since})")
if last:
    day, fg, label, trend, vol, adv, dec = last
    shown = "not enough history" if fg is None else f"{label} ({float(fg):.0f}/100)"
    print(f"  {day}: {shown}, {trend}, volatility {vol}, {adv} up / {dec} down")

# ruff: noqa: E501
"""Make today's expected-range forecast (algo.market.range_forecast, spec docs/forecast/volatility_v1_spec.md) and resolve earlier ones.
usage: build_range_forecast.py [--db URL]
Run before the open on a trading day (job `range-forecast-morning`, 08:55 IST), after the previous evening's index candles and the US closes are loaded. A forecast already made is left as it was.
Exit 1 when it could not be made because data is stale or missing (the job runner retries and alerts); exit 0 when it was made, already exists, or the market is closed."""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.market import range_forecast as rf

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    migrate(conn)
    done = rf.resolve(conn)
    out = rf.make(conn, datetime.now(UTC))
    conn.commit()
print(f"range forecast: {out.status}: {out.detail}; {done} earlier forecasts resolved")
sys.exit(1 if out.status in ("stale", "no_inputs", "too_little_history") else 0)

# ruff: noqa: E501
"""Weekly live-versus-backtest tracking for a paper account: compare its end-of-day equity with a stored backtest run of the same strategy over the same days.
Prints the report; exit 1 when the annualised tracking error is over --max-te (default 5%). With --record the result is stored in dq_result.
usage: paper_tracking.py --user UUID --run BACKTEST_RUN_ID [--db URL] [--max-te 0.05] [--record]"""

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg

from algo.core.clock import SystemClock
from algo.paper import tracking

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--user", required=True)
ap.add_argument(
    "--run",
    type=int,
    required=True,
    help="a stored backtest run (backtest_run.run_id) of the same strategy",
)
ap.add_argument("--max-te", type=float, default=0.05)
ap.add_argument("--record", action="store_true")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    live: dict[date, Decimal] = dict(
        conn.execute(
            "SELECT day, equity FROM paper_equity WHERE user_id=%s", (UUID(a.user),)
        ).fetchall()
    )
    model: dict[date, Decimal] = dict(
        conn.execute("SELECT day, equity FROM backtest_equity WHERE run_id=%s", (a.run,)).fetchall()
    )
    if not live or not model:
        sys.exit(f"nothing to compare: {len(live)} paper day(s), {len(model)} backtest day(s)")
    t = tracking.compare(live, model)
    bad = tracking.breached(t, max_tracking_error=a.max_te)
    if a.record:
        conn.execute(
            "INSERT INTO dq_result (run_at, check_name, scope, subject, status, detail) VALUES (%s,'tracking',%s,%s,%s,%s)",
            (
                SystemClock().now(),
                f"paper {a.user} vs backtest run {a.run}",
                None,
                "FAIL" if bad else "PASS",
                f"tracking error {t.tracking_error}, final gap {t.final_gap}, {t.days} days",
            ),
        )
print(
    f"{t.days} day(s) {t.first}..{t.last}: live {t.live_return}, model {t.model_return}, final gap {t.final_gap}, max daily gap {t.max_daily_gap}, tracking error {t.tracking_error} (allowed {a.max_te})"
)
sys.exit(1 if bad else 0)

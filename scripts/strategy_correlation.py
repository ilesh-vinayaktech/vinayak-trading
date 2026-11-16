# ruff: noqa: E501
"""Print the correlation of the current round's strategies, each at its own fixed setting (daily returns over the research window). Read-only.
usage: strategy_correlation.py [--threshold 0.8] [--passed-only] [--db URL]"""

import argparse
import os
import sys

import psycopg
from psycopg.types.json import Jsonb

from algo.portfolio import strategy_correlation

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--threshold", type=float, default=0.8)
ap.add_argument(
    "--passed-only", action="store_true", help="only studies whose latest verdict passed every gate"
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    rows = conn.execute(
        "SELECT e.name, e.study->'spec'->'fixed', (SELECT passed FROM validation_report r WHERE r.experiment_id = e.experiment_id ORDER BY report_id DESC LIMIT 1)"
        " FROM experiment e WHERE e.strategy_id = 'dsl' AND jsonb_typeof(e.study->'spec'->'fixed') = 'object' ORDER BY e.experiment_id"
    ).fetchall()
    series: dict[str, list[float]] = {}
    for name, fixed, passed in rows:
        if a.passed_only and not passed:
            continue
        trial = conn.execute(
            "SELECT t.returns FROM study_trial t JOIN experiment e USING (experiment_id) WHERE e.name = %s AND t.status = 'DONE' AND t.params = %s::jsonb",
            (name, Jsonb(fixed)),
        ).fetchone()
        if trial is not None:
            series[name.split(" v1")[0]] = trial[0]
if len(series) < 2:
    sys.exit("fewer than two strategies of the current round have a finished fixed-setting trial")
print(strategy_correlation.report(series, a.threshold))

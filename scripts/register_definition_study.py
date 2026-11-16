# ruff: noqa: E501
"""Register a study for a registered strategy definition, so it runs through experiments, walk-forward, cost stress and the one-time holdout. Registers only; enqueue it from the studies page / job runner.
usage: register_definition_study.py STRATEGY_ID [--version 1] --owner USER_UUID [--family 1] [--start 2020-10-01] [--end 2024-12-31] [--holdout-start 2023-10-01] [--db URL]"""

import argparse
import os
import sys
from datetime import UTC, date, datetime
from uuid import UUID

import psycopg

from algo.factory import study

ap = argparse.ArgumentParser()
ap.add_argument("strategy_id")
ap.add_argument("--version", type=int, default=1)
ap.add_argument("--owner", required=True, type=UUID)
ap.add_argument("--family", type=int, default=1)
ap.add_argument("--start", type=date.fromisoformat, default=date(2020, 10, 1))
ap.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
ap.add_argument("--holdout-start", type=date.fromisoformat, default=date(2023, 10, 1))
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    s = study.spec_for(
        conn,
        a.strategy_id,
        a.version,
        family_id=a.family,
        start=a.start,
        end=a.end,
        holdout_start=a.holdout_start,
    )
    print(
        f"registered study {study.register(conn, a.owner, s, datetime.now(UTC))}: {s.name}, {len(study.GRID['entry_share']) * len(study.GRID['max_positions'])} trials"
    )

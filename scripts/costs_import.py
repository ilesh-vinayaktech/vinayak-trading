# ruff: noqa: E501
"""Load the cost schedules in config/cost_schedules/*.json into the database (the Costs page manages them from there).

Safe to repeat: schedules already stored are never overwritten (edits made in the portal win), only new ones are added."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.backtest.costs.schedule_store import import_files

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("config/cost_schedules"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    print(f"{import_files(conn, a.dir, now=datetime.now(UTC))} new schedules imported from {a.dir}")

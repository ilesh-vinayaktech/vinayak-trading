"""Add the full set of figures (balance sheet, cash flow, every P&L line) to filings already stored.

Reads the raw XBRL from the lake, no network. Safe to repeat.
usage: backfill_fundamental_facts.py --db URL [--lake data/lake]"""

import argparse
import os
from pathlib import Path

import psycopg

from algo.data.fundamentals_ingest import backfill_facts
from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    print(f"filings re-read: {backfill_facts(conn, LocalLake(a.lake))}", flush=True)

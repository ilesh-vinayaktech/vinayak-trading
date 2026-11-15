# ruff: noqa: E501
"""Load the sector (Industry) of every stock on the newest Nifty 500 list in the lake. Insert-only and repeatable: an unchanged sector adds nothing.
usage: load_sectors.py [--db URL] [--lake data/lake]"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data import sectors

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    day, stored, unmatched = sectors.load_latest(conn, a.lake, datetime.now(UTC))
print(
    f"list of {day}: {stored} row(s) stored; {len(unmatched)} symbol(s) with no instrument"
    + (f": {', '.join(unmatched[:20])}" if unmatched else "")
)

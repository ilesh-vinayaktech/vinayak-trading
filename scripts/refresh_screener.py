# ruff: noqa: E501
"""Rebuild the stored screener table from the latest bars and filings (30-50 s). usage: refresh_screener.py [--db URL]
A step of the screener-refresh job, which runs after the bars and results have loaded."""

import argparse
import os
import sys

import psycopg

from algo.screener import snapshot

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    print(f"screener table rebuilt: {snapshot.refresh(conn)} stocks")

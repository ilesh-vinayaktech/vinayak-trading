# ruff: noqa: E501
"""Register the three pre-registered return-oriented strategy definitions (algo.factory.preregistered). Safe to run again: what exists is left alone.
usage: register_preregistered.py [--db URL] [--by NAME]"""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.factory import preregistered

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--by", default="review-2026-11-16")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    written = preregistered.register_all(conn, by=a.by, now=datetime.now(UTC))
print(f"registered {', '.join(written) if written else 'nothing new'}")

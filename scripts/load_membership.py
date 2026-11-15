# ruff: noqa: E501
"""Load the reconstructed Nifty 200 membership (docs/stage4/membership-2018) as PROVISIONAL events and a PROVISIONAL coverage declaration.
Never verifies: that is the owner's sign-off. Idempotent. usage: load_membership.py --db postgresql://... [--dir DIR] [--apply]"""

import argparse
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.membership_load import load_reconstruction

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("docs/stage4/membership-2018"))
ap.add_argument("--apply", action="store_true", help="commit; without it everything is rolled back")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
BASIS = (
    "PROVISIONAL reconstruction from NSE press releases walked back from the 2026-11-07 snapshot; matches every month-end constituent list "
    "(N50 103/103, Next50 79/79, Midcap100 48/48, derived N200 48/48). Not person-verified. Entities without an instrument (placeholders, "
    "JIOFIN before listing) are not stored: see membership_exceptions.csv."
)
with psycopg.connect(a.db) as conn:
    r = load_reconstruction(conn, directory=a.dir, index_id="NIFTY200", covered_from=date(2018, 4, 2), covered_until=date(2026, 11, 7),
                            basis=BASIS, now=datetime.now(UTC))  # fmt: skip
    print(
        f"events added {r.added}, already stored {r.existing}, effective-date clamped to announcement {r.clamped}, coverage {r.coverage_id}"
    )
    if a.apply:
        conn.commit()
        print("committed (PROVISIONAL)")
    else:
        conn.rollback()
        print("dry run: rolled back (pass --apply)")

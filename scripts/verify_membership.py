# ruff: noqa: E501
"""Mark the stored PROVISIONAL membership events and the declared coverage of one index VERIFIED, in the owner's name. Dry run unless --apply.
Needs --by (who verifies) and --record (the decision record file that is preserved with it). Verification covers MEMBERSHIP only: price
availability, corporate-action readiness and instrument identity are separate checks a strict-mode experiment must still pass.
usage: verify_membership.py --db postgresql://... --by NAME --record docs/.../VERIFICATION.md [--index NIFTY200] [--apply]"""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.universe import coverage_report, set_event_status, verify_coverage

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--index", default="NIFTY200")
ap.add_argument("--by", required=True)
ap.add_argument("--record", type=Path, required=True)
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
if not a.record.is_file():
    raise SystemExit(f"error: the decision record {a.record} does not exist")
now = datetime.now(UTC)
with psycopg.connect(a.db) as conn:
    ev = [
        r[0]
        for r in conn.execute(
            "SELECT event_id FROM index_membership_event WHERE index_id=%s AND verified_status='PROVISIONAL' ORDER BY event_id",
            (a.index,),
        )
    ]
    cov = [
        r[0]
        for r in conn.execute(
            "SELECT coverage_id FROM index_membership_coverage WHERE index_id=%s AND verified_status='PROVISIONAL' ORDER BY coverage_id",
            (a.index,),
        )
    ]
    for e in ev:
        set_event_status(conn, e, "VERIFIED", by=a.by, now=now)
    for c in cov:
        verify_coverage(conn, c, by=a.by, now=now)
    r = coverage_report(conn, a.index)
    print(
        f"events {len(ev)}, coverage {len(cov)} -> VERIFIED by {a.by}; report: {r['events']}, inconsistency {r['inconsistency']}, strict_ready {r['strict_ready']}"
    )
    if a.apply:
        conn.commit()
        print("committed")
    else:
        conn.rollback()
        print("dry run: rolled back (pass --apply)")

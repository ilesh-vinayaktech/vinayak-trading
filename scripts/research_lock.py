# ruff: noqa: E501
"""The global research holdout lock (docs/vti-alignment.md section 3).
  research_lock.py status                              the file, the anchored row, and whether research is allowed
  research_lock.py anchor --by NAME --reason "..."     record config/research_holdout.json as the lock in force (a new append-only row)
Every research reader refuses to work until the file and the newest anchored row agree. Changing the window is a deliberate act: edit
the file, then anchor it with a reason. usage: research_lock.py [--db URL] status | anchor ..."""

import argparse
import os
import sys
from datetime import UTC, datetime

import psycopg

from algo.research import holdout_lock

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("status")
an = sub.add_parser("anchor")
an.add_argument("--by", required=True)
an.add_argument("--reason", required=True)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
file_lock = holdout_lock.from_file()
with psycopg.connect(a.db, autocommit=True) as conn:
    if a.cmd == "anchor":
        lock_id = holdout_lock.anchor(
            conn, file_lock, by=a.by, reason=a.reason, now=datetime.now(UTC)
        )
        print(f"anchored lock {lock_id}")
    row = conn.execute(
        "SELECT lock_id, development_end, holdout_start, holdout_end, set_by, set_at FROM research_lock ORDER BY lock_id DESC LIMIT 1"
    ).fetchone()
    print(
        f"file: development to {file_lock.development_end}, holdout {file_lock.holdout_start} to {file_lock.holdout_end}"
    )
    print(
        "database: nothing anchored"
        if row is None
        else f"database: lock {row[0]}, development to {row[1]}, holdout {row[2]} to {row[3]}, set by {row[4]} at {row[5]}"
    )
    try:
        holdout_lock.require(conn)
        print("research is allowed")
    except holdout_lock.LockMismatch as e:
        print(f"research is REFUSED: {e}")
        sys.exit(1)

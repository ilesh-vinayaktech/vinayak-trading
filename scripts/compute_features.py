# ruff: noqa: E501
"""Materialise every USABLE feature, month by month, against one data freeze (docs/vti-phase1-spec.md item D).
Exit 1 when the input data is not ready or a month failed; a pause (paper run, paper orders, market hours) exits 0 and the next run resumes.
usage: compute_features.py [--db URL] [--freeze UUID (default: the newest)] [--from YYYY-MM-01]"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import psycopg

from algo.core.clock import SystemClock
from algo.features import job
from algo.jobs import progress
from algo.research import slot

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--freeze")
ap.add_argument("--from", dest="first", default="2020-01-01")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")


def commandlines() -> list[str]:
    return [
        p.read_bytes().replace(b"\0", b" ").decode(errors="replace")
        for p in Path("/proc").glob("[0-9]*/cmdline")
        if p.exists()
    ]


commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
).stdout.strip()
with psycopg.connect(a.db, autocommit=True) as conn, slot.hold(conn, "feature job", nice=10):
    fid = (
        a.freeze
        or (
            conn.execute(
                "SELECT freeze_id FROM data_freeze ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
            or [None]
        )[0]
    )
    if fid is None:
        sys.exit("error: no data freeze")
    try:
        with (
            psycopg.connect(
                a.db, autocommit=True
            ) as pconn,  # its own connection: each progress update shows at once
            progress.Progress(
                pconn, SystemClock(), "feature_computation", "Feature computation", 1
            ) as prog,
        ):
            r = job.run(conn, UUID(str(fid)), date.fromisoformat(a.first), datetime.now(UTC), commit,
                        busy=lambda now: job.busy_reason(now, commandlines()), progress=prog.step)  # fmt: skip
            prog.finish(
                r.status != "failed",
                f"{r.status}: {len(r.computed)} computed, {r.already} already complete, {len(r.failed)} failed"
                + (f"; paused: {r.paused_because}" if r.paused_because else ""),
            )
    except job.JobRefused as e:
        sys.exit(f"refused: {e}")
print(f"{r.status}: {len(r.computed)} computed, {r.already} already complete, {len(r.failed)} failed, skipped (not USABLE): {', '.join(r.skipped) or 'none'}"
      + (f"; paused: {r.paused_because}" if r.paused_because else ""))  # fmt: skip
for line in r.failed:
    print("  failed:", line)
sys.exit(1 if r.status == "failed" else 0)

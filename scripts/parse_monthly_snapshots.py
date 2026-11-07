"""Parse every stored monthly archive into month-end constituent snapshots (idempotent), and print
the problems the parser could not resolve.
usage: parse_monthly_snapshots.py --lake data/lake --db postgresql://..."""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.index_monthly import parse_archive
from algo.data.lake import LocalLake
from algo.data.providers.niftyindices_archive import DATASET
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, now = LocalLake(a.lake), datetime.now(UTC)
total_problems = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for part in sorted((a.lake / "raw" / "niftyindices" / DATASET).glob("dt=*")):
        d = datetime.fromisoformat(part.name[3:]).date()
        m = lake.versions("niftyindices", DATASET, d)[-1]
        stored, problems = parse_archive(conn, lake.get(m), now)
        total_problems += len(problems)
        print(
            f"{d}: {len(stored)} indices parsed"
            + (f", {len(problems)} problems" if problems else "")
        )
        for p in problems:
            print(f"    {p}")
print(f"done; {total_problems} problems")

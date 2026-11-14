# ruff: noqa: E501
"""Seal and check named data snapshots (what a run read, and proof the data under it did not change).
  data_snapshot.py create --index NIFTY200 --note "why" [--price-source kite|bhavcopy] [--price-cutoff D] [--known-at ISO]
  data_snapshot.py verify ID           recompute and name what changed (exit 1 when something did)
  data_snapshot.py show [ID]           one snapshot, or the list
A snapshot is append-only: to change it, seal a new one."""

import argparse
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from uuid import UUID

import psycopg

from algo.data import data_snapshot as ds
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
c = sub.add_parser("create")
c.add_argument("--index", default="NIFTY200", help="index_snapshot id whose stocks are pinned")
c.add_argument("--note", required=True)
c.add_argument("--price-source", default="bhavcopy", choices=ds.SOURCES)
c.add_argument("--price-cutoff", type=date.fromisoformat)
c.add_argument("--known-at", type=datetime.fromisoformat)
v = sub.add_parser("verify")
v.add_argument("id", type=UUID)
s = sub.add_parser("show")
s.add_argument("id", nargs="?", type=UUID)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    if a.cmd == "create":
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT instrument_id FROM index_snapshot WHERE index_id=%s", (a.index,)
            )
        ]
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        known = a.known_at.replace(tzinfo=a.known_at.tzinfo or UTC) if a.known_at else None
        sid = ds.create(conn, datetime.now(UTC), instruments=ids, note=a.note, price_source=a.price_source,
                        price_cutoff=a.price_cutoff, known_at=known, code_commit=commit, pins={"index": a.index})  # fmt: skip
        print(f"sealed {sid}: {len(ids)} instruments of {a.index}, source {a.price_source}")
    elif a.cmd == "verify":
        problems = ds.verify(conn, a.id)
        print(
            "\n".join(problems)
            if problems
            else f"snapshot {a.id}: every pinned input is exactly as recorded"
        )
        sys.exit(1 if problems else 0)
    elif a.id:
        snap = ds.get(conn, a.id)
        if snap is None:
            sys.exit("no such snapshot")
        snap["partitions"] = f"{len(snap['partitions'])} files in the manifest"
        snap["instrument_ids"] = f"{len(snap['instrument_ids'])} instruments"
        for k, val in snap.items():
            print(f"{k}: {val}")
    else:
        rows = conn.execute(
            "SELECT snapshot_id, created_at, cutoff_time, price_source, cardinality(instrument_ids), note FROM data_snapshot ORDER BY created_at DESC"
        ).fetchall()
        for r in rows:
            print(*r, sep="  ")
        print(f"{len(rows)} snapshot(s)")

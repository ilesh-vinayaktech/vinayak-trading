# ruff: noqa: E501  (driver script)
"""Freeze the Kite daily history we hold, and check later that it has not changed.

  freeze_kite.py take --through 2026-11-11 --note "why"   record the snapshot (per-stock rows, dates, checksum)
  freeze_kite.py verify [--id UUID]                        recompute and name every stock whose frozen rows changed (default: the latest freeze)
  freeze_kite.py show                                      list the freezes
Exit code 1 when verify finds a difference."""

import argparse
import os
import sys
from datetime import UTC, date, datetime
from uuid import UUID

import psycopg

from algo.data import freeze

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
sub = ap.add_subparsers(dest="cmd", required=True)
t = sub.add_parser("take")
t.add_argument("--through", type=date.fromisoformat, required=True)
t.add_argument("--note", required=True)
t.add_argument("--source", default="kite")
v = sub.add_parser("verify")
v.add_argument("--id", type=UUID)
sub.add_parser("show")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db, autocommit=True) as conn:
    if a.cmd == "take":
        fid = freeze.take(conn, a.source, a.through, datetime.now(UTC), a.note)
        f = freeze.get(conn, fid)
        assert f is not None
        print(
            f"frozen {f['source']} {f['dataset']} through {f['through_date']}: {f['instruments']} stocks, {f['total_rows']:,} rows (id {fid})"
        )
    elif a.cmd == "show":
        for fid, src, thr, n, rows, note, at in conn.execute(
            "SELECT freeze_id, source, through_date, instruments, total_rows, note, taken_at FROM data_freeze ORDER BY taken_at"
        ):
            print(
                f"{fid}  {src} through {thr}  {n} stocks  {rows:,} rows  taken {at:%Y-%m-%d %H:%M} UTC  {note}"
            )
    else:
        fid = a.id
        if fid is None:
            row = conn.execute(
                "SELECT freeze_id FROM data_freeze ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                sys.exit("no freeze recorded yet")
            fid = row[0]
        problems = freeze.verify(conn, fid)
        if not problems:
            print(f"freeze {fid}: every frozen row is exactly as recorded")
        else:
            names = dict(
                conn.execute(
                    "SELECT instrument_id, symbol FROM instrument WHERE instrument_id = ANY(%s)",
                    ([p["instrument_id"] for p in problems],),
                ).fetchall()
            )
            print(f"freeze {fid}: {len(problems)} stocks differ from what was frozen")
            for p in problems[:50]:
                print(f"  {names.get(p['instrument_id'], p['instrument_id'])}: {p['why']}")
            sys.exit(1)

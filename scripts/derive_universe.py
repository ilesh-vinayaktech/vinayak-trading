"""Derive Nifty 200 membership from the parsed releases and PRINT what does not reconcile.
--apply writes the reconciling instruments as PROVISIONAL membership events (no coverage declared).
usage: derive_universe.py --db postgresql://... [--apply]"""

import argparse
import os
from collections import Counter
from datetime import UTC, datetime

import psycopg

from algo.data.store.migrate import migrate
from algo.data.universe_build import derive, persist
from algo.data.universe_derive import M1, M2

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--apply", action="store_true")
ap.add_argument("--show", type=int, default=12, help="examples to print per discrepancy kind")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    report, snapshot, as_of = derive(conn)
    print(f"current official Nifty 200 snapshot: {len(snapshot)} instruments as of {as_of}")
    by = Counter(d.index_id for d in report.derived)
    print(f"derived Nifty 200 changes: {by[M2]} ({M2}, midcap=Midcap 100 from 2018-04-02), "
          f"{by[M1]} ({M1}, midcap=Full Midcap 100 before it)")  # fmt: skip
    print("\ndiscrepancies by kind:", dict(report.gaps))
    shown: Counter[str] = Counter()
    for d in report.discrepancies:
        if shown[d.kind] < a.show:
            shown[d.kind] += 1
            print(f"  {d.kind:20} {str(d.on or ''):10} {d.symbol:14} {d.detail}")
    counts = report.counts.get(M2, [])
    if counts:
        off = [(d, n) for d, n in counts if n != 200]
        print(f"\nbackward mapped-member counts at {len(counts)} change dates; "
              f"{len(off)} differ from 200 (min {min(n for _, n in counts)}, "
              f"max {max(n for _, n in counts)})")  # fmt: skip
        print("  earliest:", counts[:3], " latest:", counts[-3:])
    if a.apply:
        print(f"\nwrote {persist(conn, report, snapshot, datetime.now(UTC))} provisional events")
    else:
        print("\n(dry run: nothing written; pass --apply)")

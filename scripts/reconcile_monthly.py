"""Compare the official month-end snapshots with the press-release events, per index. Prints a
summary and writes EVERY finding (with nearby events as context) to a CSV. Nothing is corrected.
usage: reconcile_monthly.py --db postgresql://... [--out data/reports/monthly_reconciliation.csv]"""

import argparse
import csv
import os
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

from algo.data.store.migrate import migrate
from algo.data.universe_build import reconcile_monthly

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", type=Path, default=Path("data/reports/monthly_reconciliation.csv"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    snaps, diffs = reconcile_monthly(conn)
dates = sorted({s.as_of for s in snaps})
print(f"{len(snaps)} snapshots over {len(dates)} month-ends ({dates[0] if dates else '-'} .. "
      f"{dates[-1] if dates else '-'}); {len(diffs)} findings")  # fmt: skip
by = defaultdict(Counter)
for d in diffs:
    by[d.component][d.kind] += 1
for comp in sorted(by):
    print(f"  {comp:18} {dict(sorted(by[comp].items()))}")
months = Counter((d.end.year, d.end.month) for d in diffs if d.kind != "COUNT_ANOMALY")
print("worst months:", [(f"{y}-{m:02d}", n) for (y, m), n in months.most_common(8)])
a.out.parent.mkdir(parents=True, exist_ok=True)
with open(a.out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        ["kind", "component", "previous_snapshot", "snapshot", "key", "symbol", "detail", "context"]
    )
    for d in sorted(diffs, key=lambda x: (x.end, x.component, x.kind, x.key)):
        w.writerow(
            [
                d.kind,
                d.component,
                d.start or "",
                d.end,
                d.key,
                d.symbol,
                d.detail,
                " | ".join(d.context),
            ]
        )
print(f"wrote {a.out}")

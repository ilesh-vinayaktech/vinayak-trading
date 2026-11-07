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
from algo.data.universe_monthly import categorize, coverage

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
categorized = categorize(diffs)
by = defaultdict(Counter)
for d in diffs:
    by[d.component][d.kind] += 1
cats = Counter(cat for _, cat in categorized)
print("by category:", dict(sorted(cats.items())))
for comp in sorted(by):
    print(f"  {comp:18} {dict(sorted(by[comp].items()))}")
months = Counter((d.end.year, d.end.month) for d in diffs if d.kind != "COUNT_ANOMALY")
print("worst months:", [(f"{y}-{m:02d}", n) for (y, m), n in months.most_common(8)])
a.out.parent.mkdir(parents=True, exist_ok=True)
COLUMNS = ["category", "kind", "component", "previous_snapshot", "snapshot", "key", "symbol",
           "detail", "context"]  # fmt: skip
with open(a.out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(COLUMNS)
    for d, cat in sorted(
        categorized, key=lambda x: (x[0].end, x[0].component, x[0].kind, x[0].key)
    ):
        w.writerow([cat, d.kind, d.component, d.start or "", d.end, d.key, d.symbol, d.detail,
                    " | ".join(d.context)])  # fmt: skip
print(f"wrote {a.out}")
print(
    "\nCOVERAGE (confirmed = every monthly transition reconciles; strict mode must block the rest)"
)
for c in coverage(snaps, categorized):
    spans = ", ".join(f"{sp.start}..{sp.end} ({sp.months}m)" for sp in c.confirmed)
    print(
        f"  {c.component:16} {c.first}..{c.last}  {c.clean}/{c.transitions} transitions confirmed"
    )
    print(f"    confirmed spans: {spans}")
    if c.unconfirmed:
        print(f"    NOT confirmed at: {', '.join(str(d) for d in c.unconfirmed)}")

# ruff: noqa: E501
"""Apply the owner's buy-back policy (docs/adjustment-policy.md#buy-backs) to open buy-back items:
no price adjustment, recorded no_adjustment_verified. Skips a buy-back that also carries a dividend
(the dividend still matters for total return) and anything without prices or outside --scope.
usage: apply_buyback_policy.py [--scope nifty200|all] [--apply]   (dry run unless --apply)"""

import argparse
import os
import re
from datetime import UTC, datetime

import psycopg

from algo.data.review import ResolveError, resolve
from algo.data.review_worklist import worklist

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--scope", choices=("nifty200", "all"), default="nifty200")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
BY = "claude:applying owner policy 2026-11-07"
done = skipped = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    for r in worklist(conn, kind="buy")["items"]:
        if not r["has_prices"] or (a.scope == "nifty200" and not r["in_nifty200"]):
            continue
        if re.search(r"dividend", r["subject"], re.I):
            print(f"SKIP (also a dividend) {r['symbol']} {r['ex_date']}: {r['subject']}")
            skipped += 1
            continue
        print(
            f"{'APPLY' if a.apply else 'would apply'} {r['symbol']} {r['ex_date']}: {r['subject']}"
        )
        if a.apply:
            try:
                resolve(conn, symbol=r["symbol"], ex_date=datetime.fromisoformat(r["ex_date"]).date(),
                        kind="buy", method="ignore", status="no_adjustment_verified", by=BY,
                        now=datetime.now(UTC), source_type="methodology_policy",
                        source_url="docs/adjustment-policy.md#buy-backs",
                        note="Buy-back: no mechanical historical OHLC adjustment (owner policy 2026-11-07)")  # fmt: skip
            except ResolveError as e:
                print("  FAILED:", e)
                continue
        done += 1
print(f"{done} {'applied' if a.apply else 'to apply'}, {skipped} skipped")

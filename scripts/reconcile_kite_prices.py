# ruff: noqa: E501
"""Reconcile Kite's daily candles with NSE bhavcopy across every mapped stock (read-only).

For each stock whose Kite token is active: Kite's adjusted daily closes against bhavcopy closes adjusted by OUR corporate-action
records, matched by date (see algo.data.kite_compare). Prints a summary by status and the stocks that disagree, and writes one
CSV row per stock. Where the sources agree, the adjustments are corroborated by two independent sources; only the others need a person.
usage: reconcile_kite_prices.py [--db URL] [--all] [--symbols A,B] [--limit N] [--tolerance 0.01] [--out FILE.csv] [--record]
Exit 1 only for stocks that breach NOW and did not breach in the previous recorded run (an old backlog is not news every day); --record stores this run in dq_result."""

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.core.clock import SystemClock
from algo.data.kite_compare import Comparison, breaches, compare
from algo.data.quality import results
from algo.data.reader import BarReader

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--all", action="store_true", help="every mapped stock, not only those the live feed follows"
)
ap.add_argument("--symbols", default="")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--tolerance", type=Decimal, default=Decimal("0.01"))
ap.add_argument(
    "--out", type=Path, default=Path(f"data/logs/kite_reconcile_{datetime.now(UTC):%Y%m%d}.csv")
)
ap.add_argument(
    "--record",
    action="store_true",
    help="store this run in dq_result (the baseline for the next run)",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    rows = conn.execute(
        f"SELECT instrument_id, tradingsymbol FROM kite_instrument WHERE {'TRUE' if a.all else 'active'} AND instrument_id IS NOT NULL ORDER BY tradingsymbol"
    ).fetchall()
    if a.symbols:
        rows = [r for r in rows if r[1] in set(a.symbols.split(","))]
    rows = rows[: a.limit or None]
    kite, nse = BarReader(conn, source="kite"), BarReader(conn, source="nse")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    odd = []
    compared: dict[str, Comparison] = {}
    with a.out.open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(
            [
                "symbol",
                "status",
                "days",
                "outliers",
                "max_deviation",
                "step_date",
                "step_ratio",
                "explained_by_kind",
                "explained_by_ex_date",
                "explained_by_status",
            ]
        )
        for iid, sym in rows:
            r = compare(kite.load(iid), nse.load(iid), tolerance=a.tolerance)
            counts[r.status] += 1
            compared[sym] = r
            why = r.explained_by or ("", "", "")
            out.writerow(
                [
                    sym,
                    r.status,
                    r.days,
                    r.outliers,
                    f"{r.max_deviation:.4f}",
                    r.step_date or "",
                    r.step_ratio and f"{r.step_ratio:.6f}",
                    *why,
                ]
            )
            if r.status != "MATCH":
                odd.append((sym, r))
    print(
        f"{len(rows)} stocks compared (tolerance {a.tolerance}): "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    )
    for sym, r in odd[:60]:
        note = (
            f"explained by {r.explained_by[0]} ex {r.explained_by[1]} ({r.explained_by[2]})"
            if r.explained_by
            else "no recorded action nearby"
        )
        print(
            f"  {sym:14} {r.status:10} days {r.days:5} outliers {r.outliers:4} max dev {r.max_deviation:.3f}"
            + (f"  step {r.step_date} x{r.step_ratio:.4f}  {note}" if r.step_date else "")
        )
    print(f"full list: {a.out}")
    breaching = breaches(compared)
    try:
        new = results.new_breaches(conn, "kite_reconcile", breaching)
    except psycopg.errors.UndefinedTable:  # migration 075 not applied: every breach is news
        conn.rollback()
        new = sorted(breaching)
    print(f"{len(breaching)} stock(s) breach; {len(new)} new since the previous recorded run")
    for sym in new[:40]:
        print(f"  NEW {sym}: {breaching[sym]}")
if a.record:
    with psycopg.connect(a.db, autocommit=True) as w:
        results.record_reconcile(
            w,
            breaching,
            f"kite vs bhavcopy, {len(rows)} stocks, tolerance {a.tolerance}",
            SystemClock().now(),
        )
sys.exit(1 if new else 0)

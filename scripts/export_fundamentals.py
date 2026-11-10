# ruff: noqa: E501  (report/driver script: long usage and format lines)
"""READ-ONLY: export quarterly fundamentals with QoQ and YoY growth, point-in-time safe.

One row per company / basis / quarter, using the latest filing known as of --as-of (default: all filings, i.e. today).
Money columns are in Rs crore (the filings hold rupees); EPS in rupees. Growth is a fraction (0.12 = +12%), empty when
there is no comparison quarter or the base is zero/negative. `known_at_*` is the earliest moment each growth figure was
public (the later of the two filings it uses): join to prices on that, never on the quarter end.
usage: export_fundamentals.py --db URL [--out data/exports/fundamentals_growth.csv] [--basis CONSOLIDATED] [--as-of 2024-06-30T00:00:00+00:00]"""

import argparse
import csv
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.fundamentals import growth_rows, load_quarter_rows

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", type=Path, default=Path("data/exports/fundamentals_growth.csv"))
ap.add_argument("--basis", choices=("CONSOLIDATED", "STANDALONE", "BOTH"), default="BOTH")
ap.add_argument("--as-of", type=datetime.fromisoformat, default=None)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
CRORE = Decimal(10_000_000)
MONEY = ["revenue", "ebitda_proxy", "operating_profit", "pbt", "pat", "pat_owners"]
PER_SHARE = ["eps_basic", "eps_diluted"]
GROW = ["revenue", "ebitda_proxy", "pbt", "pat", "pat_owners", "eps_basic"]

with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as conn:
    rows = growth_rows(load_quarter_rows(conn), a.as_of)
if a.basis != "BOTH":
    rows = [r for r in rows if r.basis == a.basis]


def num(v: Decimal | None, scale: Decimal = Decimal(1), places: int = 2) -> str:
    return "" if v is None else str((v / scale).quantize(Decimal(1).scaleb(-places)))


a.out.parent.mkdir(parents=True, exist_ok=True)
with a.out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "basis", "period_end", "filed_at_utc", "known_at_utc", *[f"{m}_cr" for m in MONEY], *PER_SHARE,
                *[f"{m}_qoq" for m in GROW], *[f"{m}_yoy" for m in GROW], "prev_quarter_end", "prev_year_end",
                "known_at_qoq_utc", "known_at_yoy_utc", "qoq_base_not_positive", "yoy_base_not_positive"])  # fmt: skip
    for r in rows:
        w.writerow([r.symbol, r.basis, r.period_end, r.filed_at.isoformat(), r.known_at.isoformat(),
                    *[num(r.metrics.get(m), CRORE) for m in MONEY], *[num(r.metrics.get(m)) for m in PER_SHARE],
                    *[num(r.qoq.get(m), places=4) for m in GROW], *[num(r.yoy.get(m), places=4) for m in GROW],
                    r.prev_quarter_end or "", r.prev_year_end or "",
                    r.known_at_qoq.isoformat() if r.known_at_qoq else "", r.known_at_yoy.isoformat() if r.known_at_yoy else "",
                    " ".join(r.base_not_positive_qoq), " ".join(r.base_not_positive_yoy)])  # fmt: skip
print(f"{len(rows)} rows, {len({r.symbol for r in rows})} companies -> {a.out}")

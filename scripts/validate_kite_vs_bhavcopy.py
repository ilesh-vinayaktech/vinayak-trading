# ruff: noqa: E501  (report script)
"""Compare Kite 1-minute bars (rolled to days) with NSE bhavcopy daily bars, both split/bonus/price-action adjusted through
our own readers. Read-only. NSE's close is the last-30-minute average and Kite's is the last trade, so small differences are
normal; a ratio far from 1 on every day before an ex-date means Kite adjusted for something we did not (or the reverse).
Writes one CSV row per instrument-day outside tolerance and prints a summary.
usage: validate_kite_vs_bhavcopy.py --db URL [--symbols A,B] [--limit N] [--close-tol 0.02] [--vol-tol 0.10] [--out FILE.csv]"""

import argparse
import csv
import os
import statistics
import sys
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg

from algo.data.bars import Bar
from algo.data.minute_reader import minute_history
from algo.data.reader import BarReader
from algo.data.resample import resample

IST = ZoneInfo("Asia/Kolkata")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--symbols", default="")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--close-tol", type=Decimal, default=Decimal("0.02"))
ap.add_argument("--vol-tol", type=Decimal, default=Decimal("0.10"))
ap.add_argument("--out", default="kite_vs_bhavcopy.csv")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

with psycopg.connect(a.db) as conn, open(a.out, "w", newline="") as fh:
    rows = conn.execute(
        "SELECT k.instrument_id, k.tradingsymbol, min(f.window_start), max(f.window_end) FROM kite_instrument k "
        "JOIN kite_fetch f USING (instrument_id) WHERE f.status='loaded' GROUP BY 1,2 ORDER BY 2"
    ).fetchall()
    if a.symbols:
        rows = [r for r in rows if r[1] in set(a.symbols.split(","))]
    rows = rows[: a.limit or None]
    reader = BarReader(conn)
    out = csv.writer(fh)
    out.writerow(
        [
            "symbol",
            "date",
            "kite_close",
            "nse_close",
            "close_ratio",
            "kite_volume",
            "nse_volume",
            "volume_ratio",
        ]
    )
    summary = []
    for iid, sym, lo, hi in rows:
        minutes = [
            Bar(sym, h.ts, h.open, h.high, h.low, h.close, h.volume)
            for h in minute_history(conn, iid, lo, hi, adjust="split").bars
        ]
        kite = {b.ts.astimezone(IST).date(): b for b in resample(minutes, 0)}
        nse = {
            b.ts.astimezone(IST).date(): b
            for b in reader.load(iid).history(lo, hi, adjust="split").bars
        }
        days = sorted(set(kite) & set(nse))
        cr = [kite[d].close / nse[d].close for d in days if nse[d].close]
        vr = [kite[d].volume / nse[d].volume for d in days if nse[d].volume]
        bad = 0
        for d in days:
            c = kite[d].close / nse[d].close if nse[d].close else None
            v = kite[d].volume / nse[d].volume if nse[d].volume else None
            if (c is not None and abs(c - 1) > a.close_tol) or (
                v is not None and abs(v - 1) > a.vol_tol
            ):
                bad += 1
                out.writerow(
                    [
                        sym,
                        d,
                        kite[d].close,
                        nse[d].close,
                        f"{c:.4f}" if c else "",
                        kite[d].volume,
                        nse[d].volume,
                        f"{v:.4f}" if v else "",
                    ]
                )
        summary.append(
            (
                sym,
                len(days),
                len(set(kite) - set(nse)),
                statistics.median(cr) if cr else None,
                statistics.median(vr) if vr else None,
                bad,
            )
        )
cm = [float(s[3]) for s in summary if s[3]]
vm = [float(s[4]) for s in summary if s[4]]
print(
    f"instruments {len(summary)}, days compared {sum(s[1] for s in summary):,}, days outside tolerance {sum(s[5] for s in summary):,}"
)
print(
    f"median close ratio across instruments: {statistics.median(cm):.5f} (min {min(cm):.5f}, max {max(cm):.5f})"
)
print(
    f"median volume ratio across instruments: {statistics.median(vm):.5f} (min {min(vm):.5f}, max {max(vm):.5f})"
)
print(
    "most days outside tolerance:",
    [(s[0], s[5], s[1]) for s in sorted(summary, key=lambda s: -s[5])[:15]],
)
print("kite days with no NSE bar:", sum(s[2] for s in summary))

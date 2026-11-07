"""Nifty 200 PRICE vs GROSS TRI daily returns. Cumulative returns differ by design (dividends);
this checks the daily structure: TRI return >= price return, missing or misaligned sessions, the
size and concentration of the dividend wedge, and unusual days. Names the dataset hashes used.
usage: compare_price_tri.py --db postgresql://... --price 4 --tri 1 [--out data/reports/...json]"""

import argparse
import json
import os
from pathlib import Path

import psycopg

from algo.data.benchmark import levels, references
from algo.data.benchmark_compare import wedge

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--price", type=int, required=True)
ap.add_argument("--tri", type=int, required=True)
ap.add_argument("--out", type=Path, default=Path("data/reports/price_vs_tri.json"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
with psycopg.connect(a.db) as conn:
    rp, rt = references(conn, a.price), references(conn, a.tri)
    if (rp["return_type"], rt["return_type"]) != ("PRICE", "TOTAL_RETURN"):
        raise SystemExit(
            f"need PRICE and TOTAL_RETURN, got {rp['return_type']}, {rt['return_type']}"
        )
    w = wedge(levels(conn, a.price), levels(conn, a.tri))
    days = [x.day for x in w.largest]
    div = {r[0] for r in conn.execute(
        "SELECT DISTINCT ex_date FROM corporate_action WHERE kind='dividend' AND ex_date = ANY(%s)",
        (days,))}  # fmt: skip
    n_div = conn.execute(
        "SELECT count(DISTINCT ex_date) FROM corporate_action WHERE kind='dividend'"
        " AND ex_date BETWEEN %s AND %s", (rp["first"], rp["last"])).fetchone()  # fmt: skip
    base_rate = (n_div[0] if n_div else 0) / rp["observations"]
KEYS = ("benchmark_id", "name", "first", "last", "observations", "dataset_hash")
f = lambda x: round(x, 6)  # noqa: E731
report = {
    "price": {k: rp[k] for k in KEYS}, "tri": {k: rt[k] for k in KEYS},
    "note": "cumulative returns differ by design; daily structure only; not verification",
    "compared_dates": w.compared, "only_in_price": [str(d) for d in w.only_price],
    "only_in_tri": [str(d) for d in w.only_tri], "misaligned": [str(d) for d in w.misaligned],
    "price_beats_tri_beyond_rounding": [[str(d), f(x)] for d, x in w.price_beats_tri],
    "days_with_dividend_wedge": w.wedge_days, "wedge_share_in_top_5pct_days": f(w.top5pct_share),
    "wedge_by_year_pct": [[y, f(v * 100)] for y, v in w.by_year],
    "largest_wedge_days": [
        {"date": str(d.day), "tri": f(d.ret_a), "price": f(d.ret_b), "wedge": f(d.diff),
         "dividend_ex_date_in_our_actions": d.day in div} for d in w.largest],
    "dividend_ex_date_share_of_all_days": f(base_rate),
}  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=1) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "largest_wedge_days"}, indent=1))
for d in report["largest_wedge_days"]:
    print(d)

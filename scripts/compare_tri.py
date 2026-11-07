"""Nifty 200 vs Nifty 50 GROSS TRI consistency report (net is deliberately excluded).
Reads the stored series, computes returns per series BEFORE joining, writes a JSON report that names
the exact dataset hashes it was computed from. Context for each large divergence is listed, not
used to explain it away.
usage: compare_tri.py --db postgresql://... --a 1 --b 2 [--out data/reports/tri_cross_index.json]"""

import argparse
import json
import os
from pathlib import Path

import psycopg

from algo.data.benchmark import dataset_hash, levels, references
from algo.data.benchmark_compare import compare

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--a", type=int, required=True)
ap.add_argument("--b", type=int, required=True)
ap.add_argument("--sessions", type=Path, default=Path("config/exchange_sessions.json"))
ap.add_argument("--out", type=Path, default=Path("data/reports/tri_cross_index.json"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
special = {s["date"]: s["kind_status"] for s in json.loads(a.sessions.read_text())["sessions"]}
with psycopg.connect(a.db) as conn:
    refs = [references(conn, i) for i in (a.a, a.b)]
    for r in refs:
        if r["return_type"] != "TOTAL_RETURN":
            raise SystemExit(f"benchmark {r['benchmark_id']} is {r['return_type']}; gross only")
    la, lb = levels(conn, a.a), levels(conn, a.b)
    c = compare(la, lb)
    ex = {}
    for d, kind, sym in conn.execute(
        "SELECT ca.ex_date, ca.kind, i.symbol FROM corporate_action ca"
        " JOIN instrument i ON i.instrument_id=ca.instrument_id"
        " WHERE ca.ex_date = ANY(%s) AND ca.kind IN ('bonus','split')",
        ([x.day for x in c.largest],),
    ):
        ex.setdefault(str(d), []).append(f"{sym} {kind}")
    hashes = [dataset_hash(conn, i) for i in (a.a, a.b)]
f = lambda x: round(x, 6)  # noqa: E731
report = {
    "series_a": {"name": refs[0].get("name"), "benchmark_id": a.a, "dataset_hash": hashes[0]},
    "series_b": {"name": refs[1].get("name"), "benchmark_id": a.b, "dataset_hash": hashes[1]},
    "note": "consistency between related indices, not independent verification of either",
    "overlap": [str(c.overlap[0]), str(c.overlap[1])], "compared_dates": c.compared,
    "only_in_a": [str(d) for d in c.only_a], "only_in_b": [str(d) for d in c.only_b],
    "misaligned_previous_date": [str(d) for d in c.misaligned],
    "correlation": f(c.correlation), "max_abs_diff": f(c.max_abs_diff),
    "p99_abs_diff": f(c.p99_abs_diff),
    "cumulative_return": {"a": f(c.cumulative_a), "b": f(c.cumulative_b)},
    "largest_divergences": [
        {"date": str(d.day), "weekday": d.day.strftime("%a"), "a": f(d.ret_a), "b": f(d.ret_b),
         "diff": f(d.diff), "special_session": special.get(str(d.day)),
         "bonus_or_split_ex_dates": ex.get(str(d.day), [])} for d in c.largest],
}  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=1) + "\n")
print(json.dumps({k: v for k, v in report.items() if k != "largest_divergences"}, indent=1))
for d in report["largest_divergences"]:
    print(d)

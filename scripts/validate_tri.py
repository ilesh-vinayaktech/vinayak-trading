"""Validate a captured TRI dataset from the raw lake (nothing is written to the database).
Checks: base date/level, duplicates/conflicts, window bounds, positivity, gaps, largest moves,
trading-day comparison with the bhavcopy days we hold, weekend (special-session) dates, and the
published-return reconciliation. Writes a JSON report.
usage: validate_tri.py --lake data/lake --dataset tri_nifty200 --out report.json
       --factsheet config/factsheet_checks/X.json --db postgresql://..."""

import argparse
import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.benchmark_validate import (
    ReturnCheck,
    WindowResponse,
    compare_sessions,
    reconcile_returns,
    validate_series,
)  # fmt: skip
from algo.data.lake import LocalLake
from algo.data.providers.niftyindices_tri import normalized_hash, parse_response

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--dataset", required=True)
ap.add_argument("--factsheet", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", required=True, type=Path)
a = ap.parse_args()

lake = LocalLake(a.lake)
responses, all_obs = [], []
for part in sorted((a.lake / "raw" / "niftyindices" / a.dataset).glob("dt=*")):
    ws = date.fromisoformat(part.name[3:])
    m = lake.versions("niftyindices", a.dataset, ws)[-1]
    obs = parse_response(lake.get(m))  # lake.get re-verifies the stored sha256
    # the window end is not stored; the next window starts the day after, so use max(obs) bound
    responses.append((ws, obs))
    all_obs += obs
ends = [r[0] for r in responses[1:]]
wins = [
    WindowResponse(ws, (ends[i] - date.resolution) if i < len(ends) else date.max, tuple(obs))
    for i, (ws, obs) in enumerate(responses)
]  # fmt: skip
v = validate_series(wins, base_date=date(2004, 1, 1), base_level=Decimal("1000.00"))
report: dict[str, object] = {
    "dataset": a.dataset,
    "windows": len(wins),
    "observations": len(all_obs),
    "normalized_sha256": normalized_hash(all_obs),
    "checks": {c.name: {"passed": c.passed, "detail": c.detail} for c in v.checks},
    "gaps_over_5_days": [[str(x), str(y)] for x, y in v.gaps],
    "largest_moves": [[f"{float(m) * 100:.2f}%", str(d)] for m, d in v.largest_moves],
}
days = sorted(v.levels)
report["first"], report["last"] = str(days[0]), str(days[-1])
weekend = [d for d in days if d.weekday() >= 5]
report["weekend_dates"] = [f"{d} {d.strftime('%a')}" for d in weekend]
if a.db:
    with psycopg.connect(a.db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT partition FROM partition_load WHERE status IN ('loaded','noop')"
        )
        bh = {r[0] for r in rows}
    lo, hi = min(bh), max(bh)
    extra, missing = compare_sessions([d for d in days if lo <= d <= hi], sorted(bh))
    report["bhavcopy_range"] = [str(lo), str(hi)]
    report["tri_dates_without_bhavcopy"] = [f"{d} {d.strftime('%a')}" for d in extra]
    report["bhavcopy_days_without_tri"] = [str(d) for d in missing]
cfg = json.loads(a.factsheet.read_text())
checks = [ReturnCheck(c["label"], date.fromisoformat(c["base"]), date.fromisoformat(c["end"]),
                      c["kind"], Decimal(c["total_return_pct"]), Decimal(c["tolerance_pp"]))
          for c in cfg["checks"]]  # fmt: skip
res = reconcile_returns(v.levels, checks)
report["factsheet"] = {"source_sha256": cfg["source"]["sha256"], "results": [
    {"label": r.check.label, "published": str(r.check.published_pct),
     "computed": f"{float(r.computed_pct):.4f}", "difference_pp": f"{float(r.difference_pp):+.4f}",
     "tolerance_pp": str(r.check.tolerance_pp), "passed": r.passed} for r in res]}  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=1))
print(json.dumps({k: report[k] for k in report if k not in ("weekend_dates",)}, indent=1))
print("weekend dates:", report["weekend_dates"])

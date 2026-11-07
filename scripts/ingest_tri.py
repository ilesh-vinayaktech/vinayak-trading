"""Ingest a captured TRI dataset through the benchmark loader, after validating it. Fails (writes
nothing) if any check fails. Each window keeps its own raw sha256 and retrieval time. Afterwards
the published returns are re-checked on the STORED data and the report is stored separately.
usage: ingest_tri.py --lake data/lake --dataset tri_nifty200 --db postgresql://...
       --factsheet config/factsheet_checks/X.json"""

import argparse
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.benchmark import dataset_hash, ingest, levels, register, store_validation
from algo.data.benchmark_validate import (
    ReturnCheck,
    WindowResponse,
    reconcile_returns,
    validate_series,
)
from algo.data.lake import LocalLake
from algo.data.providers.niftyindices_tri import normalized_hash, parse_response
from algo.data.store.migrate import migrate

METHODOLOGY = "Nifty Indices Methodology Document, September 2026 (20260821)"
SOURCE = "niftyindices.com /BackPage/getTotalReturnIndexString"
UNRESOLVED = [
    "historical revision behaviour: only a same-day repeat was compared (identical); a later "
    "re-fetch must be compared before concluding history is never revised",
    "the factsheet is the publisher's own document, so the reconciliation is not a fully "
    "independent historical series",
    "historical methodology versions are unavailable: only the Sep 2026 document is held",
    "special sessions: weekend sessions are complete for the whole history (from the series "
    "itself); weekday special sessions before 2019-10 cannot be identified; session hours are "
    "assumed regular",
    "2022-08-08 has a benchmark value but its bhavcopy is quarantined (spreadsheet served as CSV)",
    "the factsheet CAGR day-count convention is not identified (largest difference 0.0086 pp)",
    "no net total-return series is published for Nifty 200",
]

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--dataset", required=True)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--factsheet", required=True, type=Path)
ap.add_argument("--name", default="Nifty 200 Total Return Index (gross)")
ap.add_argument("--symbol", default="NIFTY 200")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, now = LocalLake(a.lake), datetime.now(UTC)

parts = sorted((a.lake / "raw" / "niftyindices" / a.dataset).glob("dt=*"))
loaded = []
for p in parts:
    ws = date.fromisoformat(p.name[3:])
    m = lake.versions("niftyindices", a.dataset, ws)[-1]
    loaded.append((ws, m, parse_response(lake.get(m))))
starts = [w[0] for w in loaded[1:]]
wins = [
    WindowResponse(ws, (starts[i] - date.resolution) if i < len(starts) else date.max, tuple(obs))
    for i, (ws, _m, obs) in enumerate(loaded)
]  # fmt: skip
val = validate_series(wins, base_date=date(2004, 1, 1), base_level=Decimal("1000.00"))
if not val.passed:
    raise SystemExit("validation failed, nothing ingested:\n  " + "\n  ".join(val.failures()))

with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    row = conn.execute(
        "SELECT benchmark_id FROM benchmark WHERE index_symbol=%s AND return_type='TOTAL_RETURN'"
        " AND methodology_version=%s", (a.symbol, METHODOLOGY)).fetchone()  # fmt: skip
    bid = int(row[0]) if row else register(
        conn, name=a.name, provider="NSE Indices", index_symbol=a.symbol,
        return_type="TOTAL_RETURN", methodology_version=METHODOLOGY)  # fmt: skip
    conn.execute(
        "UPDATE benchmark SET valid_from=%s WHERE benchmark_id=%s", (date(2004, 1, 1), bid)
    )
    added = 0
    for _ws, m, obs in loaded:
        added += ingest(conn, bid, [(o.day, o.level) for o in obs], source=SOURCE,
                        source_timestamp=datetime.fromisoformat(m.fetched_at), raw_hash=m.checksum,
                        now=now)  # fmt: skip
    stored = levels(conn, bid)
    cfg = json.loads(a.factsheet.read_text())
    checks = [ReturnCheck(c["label"], date.fromisoformat(c["base"]), date.fromisoformat(c["end"]),
                          c["kind"], Decimal(c["total_return_pct"]), Decimal(c["tolerance_pp"]))
              for c in cfg["checks"]]  # fmt: skip
    results = reconcile_returns(stored, checks)
    all_obs = [o for _, _, obs in loaded for o in obs]
    report = {
        "series": {"index_id": "NIFTY_200", "series_type": "GROSS_TRI", "frequency": "DAILY",
                   "source": "NSE_INDICES", "start_date": "2004-01-01",
                   "end_date": str(max(stored))},
        "windows": len(loaded), "observations": len(stored),
        "raw_sha256": {str(ws): m.checksum for ws, m, _ in loaded},
        "endpoint": SOURCE,
        "methodology": METHODOLOGY,
        "checks": {c.name: {"passed": c.passed, "detail": c.detail} for c in val.checks},
        "gaps_over_5_days": [[str(x), str(y)] for x, y in val.gaps],
        "largest_moves": [[f"{float(m) * 100:.2f}%", str(d)] for m, d in val.largest_moves],
        "factsheet": [{"label": r.check.label, "published": str(r.check.published_pct),
                       "computed": f"{float(r.computed_pct):.4f}",
                       "difference_pp": f"{float(r.difference_pp):+.4f}", "passed": r.passed}
                      for r in results],
    }  # fmt: skip
    passed = val.passed and all(r.passed for r in results)
    vid = store_validation(conn, bid, report=report, passed=passed,
                           normalized_sha256=normalized_hash(all_obs),
                           factsheet_sha256=cfg["source"]["sha256"], unresolved=UNRESOLVED,
                           now=now)  # fmt: skip
    print(f"benchmark {bid}: {len(stored)} observations ({added} newly stored), "
          f"{min(stored)}..{max(stored)}")  # fmt: skip
    print(f"dataset_hash {dataset_hash(conn, bid)}")
    print(f"validation {vid}: passed={passed}; factsheet checks passed "
          f"{sum(r.passed for r in results)}/{len(results)}")  # fmt: skip

"""Ingest a captured TRI dataset through the benchmark loader, after validating it. One run
ingests ONE series: --series gross (TotalReturnsIndex -> TOTAL_RETURN) or --series net (NTR_Value ->
NET_TOTAL_RETURN); they are separate benchmarks and never mixed. Fails (writes nothing) if any
check fails. Each window keeps its own raw sha256 and retrieval time. Afterwards the published
returns are re-checked on the STORED data and the report is stored separately.
usage: ingest_tri.py --lake data/lake --dataset tri_nifty50 --db postgresql://...
       --factsheet X.json --series gross|net --symbol "NIFTY 50" --name "..."
       [--base-date D] [--base-level L] [--note T]"""

import argparse
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from algo.data.benchmark import dataset_hash, ingest, levels, register, store_validation
from algo.data.benchmark_validate import (
    REPORT_VERSION,
    ReturnCheck,
    WindowResponse,
    check_states,
    parse_acceptances,
    reconcile_returns,
    validate_net,
    validate_series,
)  # fmt: skip
from algo.data.lake import LocalLake
from algo.data.providers import niftyindices_price, niftyindices_tri
from algo.data.providers.niftyindices_tri import Observation, normalized_hash
from algo.data.store.migrate import migrate

METHODOLOGY = "Nifty Indices Methodology Document, September 2026 (20260821)"
SERIES_TYPE = {"gross": "GROSS_TRI", "net": "NET_TRI", "price": "PRICE_RETURN"}
SOURCES = {"gross": "niftyindices.com /BackPage/getTotalReturnIndexString",
           "price": "niftyindices.com /BackPage/getHistoricaldatatabletoString"}  # fmt: skip
COMMON_UNRESOLVED = [
    "historical revision behaviour: only a same-day repeat was compared (identical); a later "
    "re-fetch must be compared before concluding history is never revised",
    "the factsheet is the publisher's own document, so the reconciliation is not a fully "
    "independent historical series",
    "historical methodology versions are unavailable: only the Sep 2026 document is held",
    "special sessions: weekend sessions are complete for the whole history (from the series "
    "itself); weekday special sessions before 2019-10 cannot be identified; session hours are "
    "assumed regular",
    "2022-08-08 has a benchmark value but its bhavcopy is quarantined (spreadsheet served as CSV)",
    "the factsheet CAGR day-count convention is not identified (differences up to ~0.01 pp)",
]
NET_UNRESOLVED = [
    "the net series deducts withholding tax at the maximum rate for NON-RESIDENT institutional "
    "investors without treaty benefit (currently 23.92%) 'as applicable from time to time'; the "
    "methodology states only the current rates, the historical rates are not documented, and it is "
    "not a domestic-investor tax measure",
    "whether gross and net are independent calculations or derived from one underlying series is "
    "unknown (they are returned in the same row)",
]

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--dataset", required=True)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--factsheet", required=True, type=Path)
ap.add_argument("--series", choices=("gross", "net", "price"), required=True)
ap.add_argument("--name", required=True)
ap.add_argument("--symbol", required=True)
ap.add_argument("--base-date", type=date.fromisoformat)
ap.add_argument("--base-level", type=Decimal)
ap.add_argument(
    "--accept",
    action="append",
    default=[],
    metavar="CHECK=REASON",
    help="a failed check that was investigated; recorded in the report, never silent",
)
ap.add_argument("--note", action="append", default=[], help="extra unresolved item")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, now = LocalLake(a.lake), datetime.now(UTC)
net = a.series == "net"
parse_response = (niftyindices_price if a.series == "price" else niftyindices_tri).parse_response

loaded = []
for p in sorted((a.lake / "raw" / "niftyindices" / a.dataset).glob("dt=*")):
    ws = date.fromisoformat(p.name[3:])
    m = lake.versions("niftyindices", a.dataset, ws)[-1]
    loaded.append((ws, m, parse_response(lake.get(m))))  # lake.get re-verifies the stored sha256
all_obs = [o for _, _, obs in loaded for o in obs]
starts = [w[0] for w in loaded[1:]]


def windows(pick: bool) -> list[WindowResponse]:
    """The windows as requested; for the net series only rows that HAVE a net value."""
    out = []
    for i, (ws, _m, obs) in enumerate(loaded):
        end = (starts[i] - date.resolution) if i < len(starts) else date.max
        if pick:
            rows = tuple(
                Observation(o.day, o.net_level, None) for o in obs if o.net_level is not None
            )
        else:
            rows = tuple(obs)
        out.append(WindowResponse(ws, end, rows))
    return out


wins = windows(net)
first_day = min(o.day for w in wins for o in w.observations)
val = validate_series(wins, base_date=a.base_date or first_day, base_level=a.base_level)
checks_all = list(val.checks)
if net:
    gross = {o.day: o.level for o in all_obs}
    nv = validate_net(gross, val.levels)
    checks_all += nv.checks
    val.largest_moves, val.gaps = nv.largest_moves, nv.gaps  # net/gross ratio jumps
findings = parse_acceptances(a.accept, checks_all)
states = check_states(checks_all, findings)
if "FAIL" in states.values():
    bad = [f"{c.name}: {c.detail}" for c in checks_all if states[c.name] == "FAIL"]
    raise SystemExit("validation failed, nothing ingested:\n  " + "\n  ".join(bad))

SOURCE = SOURCES.get(a.series, SOURCES["gross"])
rtype = {"net": "NET_TOTAL_RETURN", "price": "PRICE"}.get(a.series, "TOTAL_RETURN")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    row = conn.execute(
        "SELECT benchmark_id FROM benchmark WHERE index_symbol=%s AND return_type=%s"
        " AND methodology_version=%s", (a.symbol, rtype, METHODOLOGY)).fetchone()  # fmt: skip
    bid = int(row[0]) if row else register(
        conn, name=a.name, provider="NSE Indices", index_symbol=a.symbol, return_type=rtype,
        methodology_version=METHODOLOGY)  # fmt: skip
    conn.execute("UPDATE benchmark SET valid_from=%s WHERE benchmark_id=%s", (first_day, bid))
    added = 0
    for w, (_ws, m, _o) in zip(wins, loaded, strict=True):
        added += ingest(conn, bid, [(o.day, o.level) for o in w.observations], source=SOURCE,
                        source_timestamp=datetime.fromisoformat(m.fetched_at), raw_hash=m.checksum,
                        now=now)  # fmt: skip
    stored = levels(conn, bid)
    cfg: dict[str, Any] = json.loads(a.factsheet.read_text())
    pct_field = "price_return_pct" if a.series == "price" else "total_return_pct"
    want = "gross" if a.series == "price" else a.series  # the price column sits on the gross checks
    checks = [ReturnCheck(c["label"], date.fromisoformat(c["base"]), date.fromisoformat(c["end"]),
                          c["kind"], Decimal(c[pct_field]), Decimal(c["tolerance_pp"]))
              for c in cfg["checks"]
              if c.get("series", "gross") == want and pct_field in c]  # fmt: skip
    results = reconcile_returns(stored, checks)
    report = {
        "series": {"index": cfg["index"], "index_id": cfg["index"],
                   "series_type": SERIES_TYPE[a.series],
                   "frequency": "DAILY", "source": "NSE_INDICES", "start_date": str(first_day),
                   "end_date": str(max(stored))},
        "windows": len(loaded), "observations": len(stored),
        "raw_sha256": {str(ws): m.checksum for ws, m, _ in loaded},
        "endpoint": SOURCE, "methodology": METHODOLOGY,
        "checks": {c.name: {"passed": c.passed, "detail": c.detail} for c in checks_all},
        "report_version": REPORT_VERSION, "check_states": states,
        "owner_accepted_findings": [vars(f) for f in findings],
        "gaps_over_5_days": [[str(x), str(y)] for x, y in val.gaps],
        "largest_moves": [[f"{float(m) * 100:.3f}%", str(d)] for m, d in val.largest_moves],
        "factsheet": [{"label": r.check.label, "published": str(r.check.published_pct),
                       "computed": f"{float(r.computed_pct):.4f}",
                       "difference_pp": f"{float(r.difference_pp):+.4f}", "passed": r.passed}
                      for r in results],
        "not_reproducible_from_stored_data": [
            x for x in cfg.get("not_reproducible", []) if x["series"] == a.series],
    }  # fmt: skip
    technical = all(c.passed for c in checks_all)
    report["technical_validation_passed"] = technical
    passed = technical and all(r.passed for r in results)  # an accepted failure is NOT a pass
    unresolved = COMMON_UNRESOLVED + (NET_UNRESOLVED if net else []) + a.note
    unresolved += [f"{f.state} {f.check} [{f.label}]: {f.reason}" for f in findings]
    unresolved += [
        f"{x['label']}: {x['note']}" for x in report["not_reproducible_from_stored_data"]
    ]
    vid = store_validation(conn, bid, report=report, passed=passed,
                           normalized_sha256=normalized_hash(all_obs),
                           factsheet_sha256=cfg["source"]["sha256"], unresolved=unresolved,
                           now=now)  # fmt: skip
    print(f"benchmark {bid} ({rtype}): {len(stored)} observations ({added} newly stored), "
          f"{min(stored)}..{max(stored)}")  # fmt: skip
    print(f"dataset_hash {dataset_hash(conn, bid)}")
    print(f"validation {vid}: passed={passed}; factsheet checks passed "
          f"{sum(r.passed for r in results)}/{len(results)}")  # fmt: skip
    for r in results:
        print(f"   {r.check.label:16} published {r.check.published_pct:>7} computed "
              f"{float(r.computed_pct):>9.4f} diff {float(r.difference_pp):+.4f}")  # fmt: skip

# ruff: noqa: E501
"""Historical Exchange Calendar Evidence: classify every weekday in a range from the exchange's own
legacy bhavcopy files in the lake (dataset nse/bhav_legacy), without touching any benchmark
observation. Each weekday gets a status (TRADED_CONFIRMED / CLOSED_INFERRED_BY_CHAIN /
SESSION_LIKELY_ARCHIVE_GAP / FILE_DATE_MISMATCH / UNEXAMINED) and its evidence; session kind, hours and
official holiday notices are recorded as NOT established. Deterministic output.
usage: build_calendar_evidence.py --lake data/lake --db postgresql://... --start 1999-06-30 --end 2019-09-30
       [--out docs/calendar-evidence/historical_calendar_evidence.json]"""

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import psycopg

from algo.data.benchmark import levels
from algo.data.calendar_evidence import (
    CHAIN_THRESHOLD, CLOSED, GAP, MIN_SYMBOLS, TRADED, classify, file_findings,
)  # fmt: skip
from algo.data.lake import LocalLake
from algo.data.providers.nse_bhavcopy_legacy import parse

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--start", required=True, type=date.fromisoformat)
ap.add_argument("--end", required=True, type=date.fromisoformat)
ap.add_argument(
    "--out", type=Path, default=Path("docs/calendar-evidence/historical_calendar_evidence.json")
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
root = a.lake / "raw" / "nse" / "bhav_legacy"
files, meta = {}, {}
for part in sorted(root.glob("dt=*")):
    d = date.fromisoformat(part.name[3:])
    m = lake.versions("nse", "bhav_legacy", d)[-1]
    files[d] = parse(lake.get(m))  # re-verifies the stored sha256
    meta[d] = m
missing = {date.fromisoformat(json.loads(x)["date"]) for x in (root / "capture_log.jsonl").read_text().splitlines()
           if json.loads(x)["event"] == "not_published"} - files.keys()  # fmt: skip
days = [a.start + timedelta(days=i) for i in range((a.end - a.start).days + 1)]
weekdays = [d for d in days if d.weekday() < 5]
rec = classify(weekdays, files, missing)
found, links = file_findings(files, rec)
with psycopg.connect(a.db) as conn:
    series = {
        int(b): levels(conn, int(b))
        for (b,) in conn.execute("SELECT benchmark_id FROM benchmark ORDER BY 1")
    }

per_date, conflicts = {}, []
for d in weekdays:
    r = rec[d]
    row: dict = {
        "status": r.status,
        "benchmarks_with_value": [b for b, lv in series.items() if d in lv],
    }
    if d in meta:
        row |= {"instrument_bhavcopy": {"url": meta[d].url, "sha256": meta[d].checksum, "rows": files[d].rows,
                                       "retrieved_at": meta[d].fetched_at}}  # fmt: skip
    if r.earlier:
        row["chain"] = {"earlier_session": str(r.earlier), "later_session": str(r.later),
                        "symbols_in_both": r.symbols_in_both, "close_equals_prev_close": r.symbols_equal}  # fmt: skip
    if d in links:
        a_, both_, eq_ = links[d]
        row["chain_to_previous_session"] = {"previous_session": str(a_), "symbols_in_both": both_,
                                            "close_equals_prev_close": eq_}  # fmt: skip
    per_date[str(d)] = row
    if r.status in (CLOSED, GAP) and row["benchmarks_with_value"]:
        conflicts.append(str(d))
doc = {
    "ledger": "historical_exchange_calendar_evidence", "range": [str(a.start), str(a.end)],
    "method": f"a file dated the day proves trading; a missing file proves nothing alone; closure is INFERRED only "
              f"when the confirmed sessions either side chain (PREVCLOSE == earlier CLOSE for >= {CHAIN_THRESHOLD:.0%} of "
              f">= {MIN_SYMBOLS} common symbols). Inference from exchange files, NOT an official holiday notice.",
    "established_here": {"trading_occurred": True, "session_kind": False, "opening_closing_times": False,
                         "official_holiday_notice": False, "instrument_level_data_present": True},
    "counts": dict(sorted(Counter(r["status"] for r in per_date.values()).items())),
    "weekdays": len(weekdays),
    "conflicts_closure_inferred_but_a_benchmark_has_a_value": conflicts,
    "traded_without_any_benchmark_value": sorted(d for d, r in per_date.items() if r["status"] == TRADED and not r["benchmarks_with_value"]),
    "archive_gap_dates": sorted(d for d, r in per_date.items() if r["status"] == GAP),
    "file_findings": [{"kind": f.kind, "date": str(f.day), "detail": f.detail} for f in found],
    "file_finding_counts": dict(sorted(Counter(f.kind for f in found).items())),
    "dates": per_date,
}  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
body = json.dumps(doc, indent=1, sort_keys=True) + "\n"
a.out.write_text(body)
print(json.dumps({k: v for k, v in doc.items() if k != "dates"}, indent=1, sort_keys=True)[:3000])
print("sha256", hashlib.sha256(body.encode()).hexdigest())

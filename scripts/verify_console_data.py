# ruff: noqa: E501
"""Independent check that what the console API serves equals the database and the frozen release
files. It re-derives every figure with its own SQL / file reads (not the API's query module) and
compares exact strings. Exit status 1 on any mismatch.
usage: verify_console_data.py --db postgresql://... [--api http://127.0.0.1:8000] [--docs docs]"""

import argparse
import json
import re
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", required=True)
ap.add_argument("--api", default="http://127.0.0.1:8000")
ap.add_argument("--docs", type=Path, default=Path("docs"))
a = ap.parse_args()
bad: list[str] = []
checked = 0


def api(path: str):
    with urllib.request.urlopen(a.api + path, timeout=60) as r:  # noqa: S310
        return json.load(r)


def check(label: str, got, want) -> None:
    global checked
    checked += 1
    if got != want:
        bad.append(f"{label}: api={got!r} db/file={want!r}")


conn = psycopg.connect(a.db)
q = lambda sql, *args: conn.execute(sql, args).fetchall()  # noqa: E731

# ---- dashboard: data health
d = api("/api/dashboard")["data"]
check("bars", d["bars"], q("SELECT count(*) FROM bar_1d")[0][0])
check(
    "instruments_with_bars",
    d["instruments_with_bars"],
    q("SELECT count(DISTINCT instrument_id) FROM bar_1d")[0][0],
)
check(
    "first_date",
    d["first_date"],
    str(q("SELECT min((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d")[0][0]),
)
last = q("SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d")[0][0]
check("last_date", d["last_date"], str(last))
check(
    "bars_on_last_date",
    d["bars_on_last_date"],
    q("SELECT count(*) FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date=%s", last)[0][0],
)
latest = {}
for src, ds, part, st in q(
    "SELECT source, dataset, partition, status FROM partition_load ORDER BY id"
):
    latest[(src, ds, part)] = "loaded" if st == "noop" else st
counts: dict[str, int] = {}
for st in latest.values():
    counts[st] = counts.get(st, 0) + 1
check("partition status counts", d["partitions"], counts)
check(
    "quarantined",
    d["quarantined_partitions"],
    sorted(str(p) for (_, _, p), st in latest.items() if st == "quarantined"),
)
check(
    "corporate action statuses",
    api("/api/dashboard")["corporate_actions"]["actions_by_status"],
    dict(q("SELECT status, count(*) FROM corporate_action GROUP BY 1")),
)

# ---- instruments: exact bar strings, and adjusted == raw x factor
for sym in ("RELIANCE", "TCS", "INFY", "HDFCBANK", "BAJFINANCE"):
    row = q("SELECT instrument_id, isin FROM instrument WHERE symbol=%s", sym)[0]
    iid = row[0]
    check(f"{sym} search isin", api(f"/api/instruments?q={sym}")[0]["isin"], row[1])
    raw = api(f"/api/instruments/{iid}/bars?start=2024-01-01&end=2025-12-31&adjust=none")["bars"]
    db = {
        str(t): (o, h, lo, c, v)
        for t, o, h, lo, c, v in q(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, open, high, low, close, volume FROM (SELECT DISTINCT ON (ts) * FROM bar_1d WHERE instrument_id=%s AND source='nse' ORDER BY ts, dataset_version DESC) x"
            " WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN '2024-01-01' AND '2025-12-31'",
            iid,
        )
    }
    check(f"{sym} raw bar count", len(raw), len(db))
    mism = [
        b["date"]
        for b in raw
        if (
            Decimal(b["open"]),
            Decimal(b["high"]),
            Decimal(b["low"]),
            Decimal(b["close"]),
            Decimal(b["volume"]),
        )
        != tuple(Decimal(x) for x in db[b["date"]])
    ]
    check(f"{sym} raw bars equal the database", mism, [])
    adj = api(f"/api/instruments/{iid}/bars?start=2024-01-01&end=2025-12-31&adjust=split")["bars"]
    off = [
        b["date"]
        for b in adj
        if Decimal(b["close"]) != Decimal(db[b["date"]][3]) * Decimal(b["factor"])
    ]
    check(f"{sym} adjusted close == raw close x factor", off, [])
    check(
        f"{sym} corporate actions",
        len(api(f"/api/instruments/{iid}")["actions"]),
        q("SELECT count(*) FROM corporate_action WHERE instrument_id=%s", iid)[0][0],
    )

# ---- benchmarks: coverage, levels, hashes, eligibility, findings
release_dirs = sorted(
    a.docs.glob("benchmark-release-*"),
    key=lambda p: tuple(int(x) for x in re.findall(r"\d+", p.name)),
)
ver = json.loads((release_dirs[-1] / "release.json").read_text())["release"]
audit = a.docs / ("benchmark-audit" if ver == "1.0" else f"benchmark-audit-{ver}")
elig = json.loads((audit / "benchmark_eligibility.json").read_text())["benchmarks"]
finds = json.loads((audit / "benchmark_unresolved_findings.json").read_text())["findings"]
for b in api("/api/benchmarks")["benchmarks"]:
    i = b["id"]
    n, first, lastd = q(
        "SELECT count(*), min(observation_date), max(observation_date) FROM benchmark_observation WHERE benchmark_id=%s",
        i,
    )[0]
    check(f"benchmark {i} observations", b["observations"], n)
    check(f"benchmark {i} coverage", (b["first"], b["last"]), (str(first), str(lastd)))
    series = next(k for k in elig if k.startswith(f"B{i}_"))
    check(f"benchmark {i} dataset hash vs release", b["dataset_hash"], elig[series]["dataset_hash"])
    check(f"benchmark {i} eligibility state", b["eligibility"]["state"], elig[series]["state"])
    check(
        f"benchmark {i} eligible uses",
        {u: x["eligible"] for u, x in b["eligibility"]["uses"].items()},
        {u: x["eligible"] for u, x in elig[series]["uses"].items()},
    )
    det = api(f"/api/benchmarks/{i}")
    want = [f["id"] for f in finds if "ALL" in f["applies_to"] or f"B{i}" in f["applies_to"]]
    check(f"benchmark {i} findings", [f["id"] for f in det["findings"]], want)
    lv = api(f"/api/benchmarks/{i}/levels?max_points=10000")["levels"]
    db_lv = {
        str(dt): str(v)
        for dt, v in q(
            "SELECT observation_date, close_value FROM benchmark_observation WHERE benchmark_id=%s",
            i,
        )
    }
    check(
        f"benchmark {i} levels equal the database",
        [p for p in lv if db_lv[p["date"]] != p["level"]],
        [],
    )
    check(f"benchmark {i} level count", len(lv), n)
    latest_v = q(
        "SELECT validation_id, passed FROM benchmark_validation WHERE benchmark_id=%s ORDER BY validation_id DESC LIMIT 1",
        i,
    )[0]
    check(f"benchmark {i} latest validation", det["validations"][0]["validation_id"], latest_v[0])

print(f"{checked} comparisons")
if bad:
    print("MISMATCHES:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("all figures served by the API equal the database and the frozen release files")

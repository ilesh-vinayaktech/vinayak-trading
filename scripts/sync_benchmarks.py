# ruff: noqa: E501
"""Bring every benchmark series up to yesterday: capture the missing days from NSE Indices into the lake (capture_tri.py), then
ingest and validate them (ingest_tri.py). A new index also gets its factsheet downloaded and its reconciliation checks written.
usage: sync_benchmarks.py [--db URL] [--lake data/lake] [--only KEY ...] [--delay 6]
Exit 1 if any series failed (the scheduled job then alerts); the others are still done. Series are in config/benchmark_indices.json."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.lake import LocalLake
from algo.data.providers import niftyindices_tri as tri
from algo.data.providers.niftyindices_factsheet import build_checks, parse
from algo.data.providers.niftyindices_price import parse_response as parse_price

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--only", nargs="*", default=[])
ap.add_argument("--delay", default="6")
ap.add_argument(
    "--reingest",
    action="store_true",
    help="ingest and validate again even when nothing new was captured",
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
cfg = json.loads(Path("config/benchmark_indices.json").read_text())
yesterday = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)
lake = LocalLake(a.lake)
NI = a.lake / "raw" / "niftyindices"


def run(*args: str) -> int:
    return subprocess.run([sys.executable, *args], check=False).returncode


def captured_to(dataset: str) -> date | None:
    """The last day a stored window asked for (windows are never extended, so the next one starts the day after)."""
    log = NI / dataset / "capture_log.jsonl"
    if not log.exists():
        return None
    ends = [
        date.fromisoformat(j["what"].split("..")[1])
        for j in map(json.loads, log.read_text().splitlines())
        if j.get("event") == "stored"
    ]
    return max(ends, default=None)


def capture(dataset: str, index: str, kind: str) -> bool | None:
    """True: new days stored. None: already up to date. False: stopped."""
    last = captured_to(dataset)
    start = date.fromisoformat(cfg["start"]) if last is None else last + timedelta(days=1)
    if start > yesterday:
        return None
    return run("scripts/capture_tri.py", "--lake", str(a.lake), "--index", index, "--dataset", dataset,
               "--kind", kind, "--start", str(start), "--end", str(yesterday), "--delay", a.delay) == 0  # fmt: skip


def stored_days(dataset: str, kind: str) -> set[date]:
    parse_one = parse_price if kind == "price" else tri.parse_response
    out: set[date] = set()
    for p in sorted((NI / dataset).glob("dt=*")):
        m = lake.versions("niftyindices", dataset, date.fromisoformat(p.name[3:]))[-1]
        out |= {o.day for o in parse_one(lake.get(m))}
    return out


def factsheet(e: dict, dataset: str) -> Path:
    """config/factsheet_checks/<key>_<as of>.json, made once from the index's factsheet PDF (kept untouched in the lake)."""
    key = e["key"]
    have = sorted(Path("config/factsheet_checks").glob(f"{key}_*.json"))
    if have:
        return have[-1]
    url = f"https://www.niftyindices.com/Factsheet/{e['factsheet']}.pdf"
    data = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90
    ).read()  # noqa: S310
    if data[:4] != b"%PDF":
        raise RuntimeError(f"{url}: not a PDF")
    text = subprocess.run(
        ["pdftotext", "-layout", "-", "-"], input=data, capture_output=True, check=True
    ).stdout.decode()
    as_of, rows = parse(text)
    lake.put("niftyindices", f"factsheet_{key}", as_of, data, url=url, fetched_at=datetime.now(UTC))
    checks = build_checks(as_of, rows["total"], stored_days(dataset, "tri"))
    if not checks:
        raise RuntimeError(f"{key}: no factsheet figure falls inside the stored history")
    out = Path(f"config/factsheet_checks/{key}_{as_of}.json")
    out.write_text(json.dumps({
        "index": e["index"].upper().replace(" ", "_"), "as_of": str(as_of),
        "source": {"dataset": f"factsheet_{key}", "sha256": hashlib.sha256(data).hexdigest(), "url": url, "document_date": str(as_of)},
        "tolerance_notes": "cumulative returns are published to 2 decimals (+/-0.005 pp); CAGR also depends on the unstated day-count convention (+/-0.02 pp); the difference is always reported. The since-inception figure is not checked: our series starts later than the index.",
        "checks": checks, "not_reproducible": [],
    }, indent=1) + "\n")  # fmt: skip
    return out


def ingest(s: dict, fs: Path) -> bool:
    args = ["scripts/ingest_tri.py", "--lake", str(a.lake), "--dataset", s["dataset"], "--db", a.db, "--factsheet", str(fs),
            "--series", s["series"], "--symbol", s["symbol"], "--name", s["name"]]  # fmt: skip
    if s.get("base"):
        args += ["--base-date", s["base"][0], "--base-level", s["base"][1]]
    for x in s.get("accept", []):
        args += ["--accept", x]
    return run(*args) == 0


def has_validation(s: dict) -> bool:
    rtype = {"net": "NET_TOTAL_RETURN", "price": "PRICE"}.get(s["series"], "TOTAL_RETURN")
    with psycopg.connect(a.db) as c:
        return c.execute(
            "SELECT 1 FROM benchmark_validation v JOIN benchmark b USING (benchmark_id) WHERE b.index_symbol=%s AND b.return_type=%s LIMIT 1",
            (s["symbol"], rtype)).fetchone() is not None  # fmt: skip


def pinned_ok(s: dict) -> bool:
    """The acceptances are the owner's, for the findings they reviewed: fail when the stored finding is a different one."""
    with psycopg.connect(a.db) as c:
        row = c.execute(
            "SELECT v.report->'owner_accepted_findings' FROM benchmark_validation v JOIN benchmark b USING (benchmark_id)"
            " WHERE b.index_symbol=%s AND b.return_type='NET_TOTAL_RETURN' ORDER BY validation_id DESC LIMIT 1", (s["symbol"],)).fetchone()  # fmt: skip
    got = {f["check"]: f["detail_sha256"] for f in (row[0] if row else [])}
    return got == s["pinned"]


series = list(cfg["legacy"]) + [
    {"dataset": f"tri_{e['key']}", "index": e["index"], "kind": "tri", "series": "gross", "symbol": e["index"].upper(),
     "name": f"{e['index']} Total Return Index (gross)", "entry": e} for e in cfg["indices"]
]  # fmt: skip
failed: list[str] = []
done_capture: dict[str, bool | None] = {}
for s in series:
    label = s["dataset"] + ("/net" if s["series"] == "net" else "")
    if a.only and not any(k in s["dataset"] for k in a.only):
        continue
    print(f"== {label}", flush=True)
    try:
        if s["dataset"] not in done_capture:
            done_capture[s["dataset"]] = capture(s["dataset"], s["index"], s["kind"])
        if done_capture[s["dataset"]] is False:
            failed.append(f"{label}: capture stopped")
            continue
        if done_capture[s["dataset"]] is None and has_validation(s) and not a.reingest:
            print("up to date")  # no new days: no new validation record either
            continue
        fs = Path(s["factsheet"]) if "factsheet" in s else factsheet(s["entry"], s["dataset"])
        if not ingest(s, fs):
            failed.append(f"{label}: ingest refused (see above)")
        elif s.get("pinned") and not pinned_ok(s):
            failed.append(f"{label}: a net/gross finding differs from the one the owner reviewed")
    except Exception as e:  # one series never stops the others
        failed.append(f"{label}: {type(e).__name__}: {e}")
print(f"\n{len(failed)} failed" + "".join(f"\n  {f}" for f in failed))
sys.exit(1 if failed else 0)

# ruff: noqa: E501
"""Capture NSE's legacy bhavcopy for sessions that only the benchmark evidences, plus the sessions
either side of each (to chain PREVCLOSE). Sequential, slow, resumable; every raw archive is stored
untouched in the lake (dataset bhav_legacy); a 404 is recorded (not retried, not worked around); any
other refusal stops the run. Writes docs/session-evidence/legacy_bhavcopy_check.json.
usage: capture_legacy_bhav.py --lake data/lake --db postgresql://... [--delay 6]
       [--weekdays START END [--phase holidays|all]]   (default: the listed sessions)"""

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.providers.nse_bhavcopy_legacy import chain, parse, url
from algo.data.providers.nse_client import NotPublished, NseClient, NseHttpError

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--sessions", type=Path, default=Path("config/exchange_sessions.json"))
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--weekdays",
    nargs=2,
    type=date.fromisoformat,
    metavar=("START", "END"),
    help="instead of the listed sessions: every weekday in the range",
)
ap.add_argument(
    "--phase",
    choices=("holidays", "all"),
    default="holidays",
    help="holidays: weekdays no benchmark series has a value for, plus their neighbours",
)
ap.add_argument("--delay", type=float, default=6.0)
ap.add_argument(
    "--out", type=Path, default=Path("docs/session-evidence/legacy_bhavcopy_check.json")
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, client = LocalLake(a.lake), NseClient(min_interval=a.delay)
DS = "bhav_legacy"
log_path = a.lake / "raw" / "nse" / DS / "capture_log.jsonl"
log_path.parent.mkdir(parents=True, exist_ok=True)
missing_log: dict[str, str] = {}
if log_path.exists():
    for line in log_path.read_text().splitlines():
        e = json.loads(line)
        if e["event"] == "not_published":
            missing_log[e["date"]] = e["url"]


def log(**kw: object) -> None:
    kw["at"] = datetime.now(UTC).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(kw) + "\n")


def have(d: date) -> bool:
    return bool(lake.versions("nse", DS, d))


def fetch(d: date) -> bool:
    """True if a file is stored for d. A 404 is recorded and means 'no file'."""
    if have(d):
        return True
    if d.isoformat() in missing_log:
        return False
    try:
        raw = client.get(url(d))
    except NotPublished:
        log(event="not_published", date=d.isoformat(), url=url(d))
        missing_log[d.isoformat()] = url(d)
        return False
    except NseHttpError as e:
        log(event="refused", date=d.isoformat(), status=e.status)
        sys.exit(f"STOPPED: {d}: HTTP {e.status}; not working around it")
    lake.put("nse", DS, d, raw, url=url(d), fetched_at=datetime.now(UTC))
    log(event="stored", date=d.isoformat(), url=url(d), bytes=len(raw))
    return True


def neighbour(d: date, step: int) -> date | None:
    """Nearest weekday session either side that has a file (a 404 on a holiday moves on)."""
    x = d
    for _ in range(6):
        x += timedelta(days=step)
        if x.weekday() < 5 and fetch(x):
            return x
    return None


if a.weekdays:
    from algo.data.benchmark import levels

    with psycopg.connect(a.db) as conn:
        have_value: set[date] = set()
        for (bid,) in conn.execute("SELECT benchmark_id FROM benchmark"):
            have_value |= set(levels(conn, bid))
    start, end = a.weekdays
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5]
    cand = [d for d in days if d not in have_value]
    order = cand + ([d for d in days if d in have_value] if a.phase == "all" else [])
    print(
        f"{len(days)} weekdays, {len(cand)} with no benchmark value; fetching {len(order)}",
        flush=True,
    )
    for i, d in enumerate(order, 1):
        got = fetch(d)
        if not got and d in cand:
            neighbour(d, -1), neighbour(d, 1)  # the sessions either side, to chain
        if i % 25 == 0 or d in cand:
            print(i, d, "file" if got else "no file", flush=True)
    raise SystemExit(0)

with psycopg.connect(a.db) as conn:
    traded = {r[0] for r in conn.execute(
        "SELECT DISTINCT partition FROM partition_load WHERE dataset='bhav' AND status IN ('loaded','noop')")}  # fmt: skip
targets = [date.fromisoformat(s["date"]) for s in json.loads(a.sessions.read_text())["sessions"]
           if date.fromisoformat(s["date"]) not in traded]  # fmt: skip
results = []
for d in sorted(targets):
    here = fetch(d)
    prev_d, next_d = (neighbour(d, -1), neighbour(d, 1)) if here else (None, None)
    entry: dict = {"date": str(d), "weekday": d.strftime("%A"), "url": url(d), "file_stored": here}
    if here:
        m = lake.versions("nse", DS, d)[-1]
        f = parse(lake.get(m))
        entry |= {"sha256": m.checksum, "retrieved_at": m.fetched_at, "bytes": m.size,
                  "rows": f.rows, "file_dates": sorted(str(x) for x in f.days),
                  "existence_confirmed": f.days == {d}}  # fmt: skip
        for label, nd, step in (("previous_session", prev_d, -1), ("next_session", next_d, 1)):
            if nd is None:
                entry[label] = None
                continue
            g = parse(lake.get(lake.versions("nse", DS, nd)[-1]))
            both, eq = chain(g.close, f.prev_close) if step < 0 else chain(f.close, g.prev_close)
            entry[label] = {"date": str(nd), "file_dates": sorted(str(x) for x in g.days),
                            "symbols_in_both": both, "close_equals_prev_close": eq}  # fmt: skip
    results.append(entry)
    print(entry["date"], entry["weekday"], "file" if here else "NO FILE",
          entry.get("existence_confirmed"), entry.get("rows"), flush=True)  # fmt: skip
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps({
    "note": "NSE legacy bhavcopy archive; confirms that the exchange traded on the date. It does not "
            "establish the purpose of the session or its opening and closing times.",
    "dates_checked": len(results), "results": results}, indent=1, sort_keys=True) + "\n")  # fmt: skip

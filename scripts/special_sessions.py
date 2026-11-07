"""Special exchange sessions, from evidence.
  --build   list the dates on which the index series has a value although a Monday-Friday calendar
            says closed: every weekend date, plus weekday dates inside our bar history whose
            bhavcopy was 'not_published' (a holiday that nevertheless has an index value).
            Writes the evidence file.
  --fetch   for those dates inside our bar history, fetch the official bhavcopy (sequential, slow)
            and load it through the normal pipeline with a calendar that includes the sessions.
usage: special_sessions.py --lake data/lake --db postgresql://... (--build|--fetch)
       [--dataset tri_nifty200 tri_nifty50]"""

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.pipeline import backfill, run_partition
from algo.data.providers.niftyindices_tri import normalized_hash, parse_response
from algo.data.providers.nse_bhavcopy import NseBhavcopy, file_date
from algo.data.providers.nse_client import NseClient
from algo.data.sessions import build_entries, calendar

CONFIG = Path("config/exchange_sessions.json")
ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dataset", nargs="+", default=["tri_nifty200"])
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--build", action="store_true")
g.add_argument("--fetch", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, now = LocalLake(a.lake), datetime.now(UTC)

if a.build:
    # every day any listed series has a value; the entry cites the FIRST series that has it
    obs: dict[date, str] = {}
    digests: dict[str, str] = {}
    for ds in a.dataset:
        got = []
        for part in sorted((a.lake / "raw" / "niftyindices" / ds).glob("dt=*")):
            ws = date.fromisoformat(part.name[3:])
            got += parse_response(lake.get(lake.versions("niftyindices", ds, ws)[-1]))
        digests[ds] = normalized_hash(got)
        for o in got:
            obs.setdefault(o.day, ds)
    entries = []
    for ds in a.dataset:
        evidence = (
            f"{ds}: the index has a value on this date (it is computed on every day the "
            "capital market segment is open - Nifty Indices methodology, Sep 2026)"
        )
        entries += build_entries((d for d, src in obs.items() if src == ds), evidence, digests[ds])
    with psycopg.connect(a.db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT partition FROM partition_load WHERE status='not_published'"
        )
        unpublished = {r[0] for r in rows}
    for d in sorted(set(obs) & unpublished):
        if d.weekday() < 5:
            entries.append({
                "date": str(d), "weekday": d.strftime("%A"), "kind": "SPECIAL",
                "kind_status": "UNCONFIRMED (weekday, TRI value, no bhavcopy: probably Muhurat)",
                "hours": None, "hours_status": "UNKNOWN (regular hours assumed for bar visibility)",
                "evidence": f"{obs[d]}: value on a weekday with no bhavcopy",
                "evidence_sha256": digests[obs[d]],
            })  # fmt: skip
    entries.sort(key=lambda e: e["date"])
    CONFIG.write_text(json.dumps({
        "exchange": "NSE_CM", "derived_from": a.dataset, "normalized_sha256": digests,
        "limitation": "weekday special sessions before the bar history starts (2019-10) cannot be "
                      "identified without historical holiday lists; weekend sessions are complete "
                      "for the whole TRI history",
        "sessions": entries}, indent=1) + "\n")  # fmt: skip
    print(f"wrote {CONFIG}: {len(entries)} sessions")
else:
    cal = calendar(CONFIG)
    sessions = [
        d for d in sorted(json.loads(CONFIG.read_text())["sessions"], key=lambda e: e["date"])
    ]
    targets = [date.fromisoformat(s["date"]) for s in sessions if s["date"] >= "2019-10-01"]
    provider = NseBhavcopy(NseClient(min_interval=6.0).get, cal)
    with psycopg.connect(a.db, autocommit=True) as conn:
        for d in targets:
            backfill(
                conn, lake, provider, "bhav", d, d, now, is_trading_day=lambda _d: True,
                progress=lambda day, st: print(f"{day} {day.strftime('%a')}: {st}"),
            )  # fmt: skip

    # A Muhurat session's data can sit in the NEXT holiday's file (DATE1 = the session date). Look
    # for a stored file that really holds the date; load it for that date with its TRUE source url.
    class Recovered(NseBhavcopy):
        def __init__(self, raw: bytes, url: str) -> None:
            super().__init__(lambda _u: raw, cal)
            self._raw, self._url = raw, url

        def fetch(self, dataset: str, d: date) -> bytes:
            return self._raw

        def url(self, dataset: str, d: date) -> str:
            return self._url

    with psycopg.connect(a.db, autocommit=True) as conn:
        for d in targets:
            loaded = conn.execute(
                "SELECT 1 FROM partition_load WHERE source='nse' AND dataset='bhav'"
                " AND partition=%s AND status IN ('loaded','noop')", (d,)).fetchone()  # fmt: skip
            if loaded:
                continue
            for k in range(1, 4):
                vs = lake.versions("nse", "bhav", d + timedelta(days=k))
                for m in reversed(vs):
                    raw = lake.get(m)
                    if file_date(raw) == d:
                        r = run_partition(conn, lake, Recovered(raw, m.url), "bhav", d, now)
                        print(f"{d} {d.strftime('%a')}: recovered from {m.url}")
                        print(f"    -> {r.status}, {r.rows} rows")
                        break
                else:
                    continue
                break
            else:
                print(f"{d}: no stored file holds this date")

# ruff: noqa: E501
"""Has NSE Indices revised history? Re-request, with the exact request body, every window already stored in the lake for the given
datasets and compare the DATA (normalized hash, observation by observation) with what was stored. Politely slow; stops on any refusal.
Writes docs/benchmark-evidence/revision_check_<date>.json. Exit 1 if any window differs.
usage: check_revisions.py --lake data/lake --dataset tri_nifty200 [--dataset ...] [--delay 6]"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

from algo.data.lake import LocalLake
from algo.data.providers import niftyindices_price as price_ep
from algo.data.providers import niftyindices_tri as tri_ep
from algo.data.providers.niftyindices_tri import normalized_hash

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
ap = argparse.ArgumentParser()
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--dataset", action="append", required=True)
ap.add_argument("--delay", type=float, default=6.0)
ap.add_argument("--out", type=Path, default=Path("docs/benchmark-evidence"))
a = ap.parse_args()
lake, today = LocalLake(a.lake), datetime.now(UTC).date()
report: dict[str, object] = {"checked_on": str(today), "datasets": {}}
different = 0
for ds in a.dataset:
    ep = price_ep if ds.startswith("price_") else tri_ep
    log = [
        json.loads(x)
        for x in (a.lake / "raw" / "niftyindices" / ds / "capture_log.jsonl")
        .read_text()
        .splitlines()
    ]
    bodies = {
        j["what"].split("..")[0]: j["request_body"] for j in log if j.get("event") == "stored"
    }
    out = []
    for p in sorted((a.lake / "raw" / "niftyindices" / ds).glob("dt=*")):
        ws = date.fromisoformat(p.name[3:])
        m = lake.versions("niftyindices", ds, ws)[-1]
        stored = ep.parse_response(lake.get(m))
        time.sleep(a.delay)
        req = urllib.request.Request(
            ep.ENDPOINT,
            data=bodies[str(ws)].encode(),
            headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310
                again = ep.parse_response(bytes(r.read()))
        except (urllib.error.URLError, TimeoutError) as e:
            sys.exit(f"STOPPED at {ds} {ws}: {e}")
        same = normalized_hash(stored) == normalized_hash(again)
        different += not same
        out.append(
            {
                "window_start": str(ws),
                "stored_observations": len(stored),
                "refetched_observations": len(again),
                "stored_fetched_at": m.fetched_at,
                "identical": same,
            }
        )
        print(
            f"{ds} {ws}: {len(stored)} vs {len(again)} {'identical' if same else 'DIFFERENT'}",
            flush=True,
        )
    report["datasets"][ds] = out  # type: ignore[index]
report["windows"] = sum(len(v) for v in report["datasets"].values())  # type: ignore[attr-defined]
report["different"] = different
a.out.mkdir(parents=True, exist_ok=True)
(a.out / f"revision_check_{today}.json").write_text(json.dumps(report, indent=1) + "\n")
print(f"{report['windows']} windows re-fetched, {different} differ")
sys.exit(1 if different else 0)

"""Capture an index's Total Returns Index history from NSE Indices in non-overlapping windows
of at most 365 days, each raw response stored UNTOUCHED in the lake. Sequential, politely slow,
stops at once on any refusal, resumable. Every request is logged (body, status, bytes, rows,
sha256, normalized hash).
usage: capture_tri.py --lake data/lake --index "Nifty 200" --dataset tri_nifty200
       [--kind tri|price] [--start 2004-01-01]"""

import argparse
import hashlib
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
from algo.data.providers.niftyindices_archive import OK, RETRY, backoff_seconds, classify
from algo.data.providers.niftyindices_tri import TriError, normalized_hash, request_body, windows

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--index", required=True)
ap.add_argument("--dataset", required=True)
ap.add_argument("--kind", choices=("tri", "price"), default="tri")
ap.add_argument("--start", default="2004-01-01", type=date.fromisoformat)
ap.add_argument("--end", default=None, type=date.fromisoformat)
ap.add_argument("--delay", default=6.0, type=float)
a = ap.parse_args()
ep = price_ep if a.kind == "price" else tri_ep
ENDPOINT, ENDPOINT_VERSION, PARSER_VERSION = ep.ENDPOINT, ep.ENDPOINT_VERSION, ep.PARSER_VERSION
parse_response = ep.parse_response
end = a.end or datetime.now(UTC).date()
lake = LocalLake(a.lake)
log_path = a.lake / "raw" / "niftyindices" / a.dataset / "capture_log.jsonl"
log_path.parent.mkdir(parents=True, exist_ok=True)


def log(**kw: object) -> None:
    kw["at"] = datetime.now(UTC).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(kw) + "\n")


def fetch(body: bytes, what: str) -> tuple[int, bytes]:
    for attempt in range(1, 4):
        time.sleep(a.delay)
        req = urllib.request.Request(ENDPOINT, data=body, headers={
            "User-Agent": UA, "Content-Type": "application/json; charset=utf-8"})  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310
                status, data = r.status, bytes(r.read())
        except urllib.error.HTTPError as e:
            status, data = e.code, e.read() or b""
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(what=what, event="network_error", attempt=attempt, error=str(e))
            if attempt == 3:
                sys.exit(f"STOPPED: {what}: network trouble persisted")
            time.sleep(backoff_seconds(attempt))
            continue
        verdict = classify(status, "", data[:4000])
        if verdict == OK:
            return status, data
        log(what=what, event=verdict, status=status)
        if verdict == RETRY and attempt < 3:
            time.sleep(backoff_seconds(attempt))
            continue
        sys.exit(f"STOPPED: {what}: HTTP {status} ({verdict}); not working around it")
    sys.exit(f"STOPPED: {what}: retries exhausted")


got = skipped = 0
for ws, we in windows(a.start, end):
    if lake.versions("niftyindices", a.dataset, ws):
        skipped += 1
        continue
    body = request_body(a.index, ws, we)
    status, data = fetch(body, f"{ws}..{we}")
    lake.put("niftyindices", a.dataset, ws, data, url=ENDPOINT, fetched_at=datetime.now(UTC))
    try:
        obs = parse_response(data)
    except TriError as e:
        log(
            what=f"{ws}..{we}",
            event="parse_error",
            error=str(e),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        sys.exit(f"STOPPED: {ws}..{we}: response stored but refused: {e}")
    outside = [o.day for o in obs if not ws <= o.day <= we]
    days = [o.day for o in obs]
    first, last = (min(days), max(days)) if days else ("", "")
    log(what=f"{ws}..{we}", event="stored", index=a.index, request_body=body.decode(),
        status=status, bytes=len(data), rows=len(obs), sha256=hashlib.sha256(data).hexdigest(),
        normalized_sha256=normalized_hash(obs), endpoint_version=ENDPOINT_VERSION,
        parser_version=PARSER_VERSION, outside_window=[str(d) for d in outside],
        first=str(first), last=str(last))  # fmt: skip
    got += 1
    flag = f"  OUTSIDE WINDOW: {outside}" if outside else ""
    print(f"{ws}..{we}: {len(obs):>4} rows  {first} .. {last}{flag}")
print(f"done: stored {got}, already present {skipped}")

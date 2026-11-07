"""Download NSE Indices' monthly 'Market Capitalisation & Weightage' ZIPs (month-end constituents of
each index) into the raw lake, UNCHANGED, one at a time and slowly.

Safeguards: sequential; fixed delay between requests; STOP at once on 403/429/CAPTCHA/any refusal
(never worked around); retries only for transient network trouble with exponential backoff; every
ZIP verified (opens, CRC, holds PDFs) before it is stored; resumable (stored months are skipped);
every request logged (status, content length, sha256) to capture_log.jsonl beside the data.
usage: capture_monthly_archive.py --lake data/lake [--start 2017-01] [--end 2026-10] [--delay 7]"""

import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from algo.data.lake import LocalLake
from algo.data.providers.niftyindices_archive import (
    DATASET,
    OK,
    RETRY,
    backoff_seconds,
    check_zip,
    classify,
    month_end,
    month_label,
    month_range,
)  # fmt: skip

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BASE = "https://www.niftyindices.com"
PAGE = f"{BASE}/reports/historical-data"
LIST_URL = f"{BASE}/reports/historical-data/Index/"
RETRIES = 3


class Stop(Exception):
    pass


def ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)


ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--start", default="2017-01", type=ym)
ap.add_argument("--end", default="2026-10", type=ym)
ap.add_argument("--delay", default=7.0, type=float)
a = ap.parse_args()

lake = LocalLake(a.lake)
log_path = a.lake / "raw" / "niftyindices" / DATASET / "capture_log.jsonl"
log_path.parent.mkdir(parents=True, exist_ok=True)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def log(**kw: object) -> None:
    kw["at"] = datetime.now(UTC).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(kw) + "\n")


def request(req: urllib.request.Request, what: str) -> tuple[int, str, bytes, str | None]:
    """One HTTP call with retry for transient trouble only. Any refusal raises Stop."""
    for attempt in range(1, RETRIES + 1):
        time.sleep(a.delay)
        try:
            with opener.open(req, timeout=90) as r:  # noqa: S310
                status, ctype, body = r.status, r.headers.get("Content-Type", ""), bytes(r.read())
                clen = r.headers.get("Content-Length")
        except urllib.error.HTTPError as e:
            status, ctype, body, clen = e.code, "", e.read() or b"", None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(what=what, event="network_error", attempt=attempt, error=str(e))
            if attempt == RETRIES:
                raise Stop(f"{what}: network trouble persisted after {RETRIES} tries") from e
            time.sleep(backoff_seconds(attempt))
            continue
        verdict = classify(
            status, ctype, body[:4000] if "json" in ctype or "html" in ctype else b""
        )
        if verdict == OK:
            return status, ctype, body, clen
        log(what=what, event=verdict, status=status, content_type=ctype)
        if verdict == RETRY and attempt < RETRIES:
            time.sleep(backoff_seconds(attempt))
            continue
        raise Stop(f"{what}: HTTP {status} ({verdict}); stopping, not working around it")
    raise Stop(f"{what}: exhausted retries")


def start_session() -> None:
    request(urllib.request.Request(PAGE, headers={"User-Agent": UA}), "session")


def listing(label: str) -> str | None:
    body = json.dumps({"SelectedReportType": "4", "SelectedDate": "", "MonthYear": label}).encode()
    hdr = {"User-Agent": UA, "Content-Type": "application/json; charset=utf-8", "Referer": PAGE,
           "X-Requested-With": "XMLHttpRequest"}  # fmt: skip
    for _ in range(2):  # one session refresh allowed
        _, _, raw, _ = request(
            urllib.request.Request(LIST_URL, data=body, headers=hdr), f"list {label}"
        )
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            start_session()
            continue
        files = doc.get("data") or []
        return str(files[0]["DownloadLink"]) if doc.get("success") and files else None
    raise Stop(f"list {label}: the listing endpoint stopped returning JSON")


try:
    start_session()
    got = skipped = missing = 0
    for y, m in month_range(a.start, a.end):
        label, d = month_label(y, m), month_end(y, m)
        if lake.versions("niftyindices", DATASET, d):
            skipped += 1
            continue
        link = listing(label)
        if link is None:
            log(what=label, event="unavailable")
            missing += 1
            print(f"{label}: not offered")
            continue
        url = BASE + link
        status, ctype, data, clen = request(
            urllib.request.Request(url, headers={"User-Agent": UA}), label
        )
        check = check_zip(data)
        if not check.ok:
            raise Stop(f"{label}: downloaded file rejected: {check.reason}")
        m_ = lake.put("niftyindices", DATASET, d, data, url=url, fetched_at=datetime.now(UTC))
        log(what=label, event="stored", status=status, content_type=ctype, content_length=clen,
            bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), members=len(check.names),
            version=m_.version)  # fmt: skip
        got += 1
        print(
            f"{label}: stored {len(data):>9} bytes, {len(check.names)} files, "
            f"sha256={m_.checksum[:12]}"
        )
    print(f"done: stored {got}, already present {skipped}, not offered {missing}")
except Stop as e:
    log(event="stopped", reason=str(e))
    sys.exit(f"STOPPED: {e}")

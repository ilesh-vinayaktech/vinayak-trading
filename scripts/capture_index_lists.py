# ruff: noqa: E501
"""Store the official constituent lists of the sector and broad indices the portal shows (algo/data/index_members.py FILES) UNTOUCHED in the raw lake.
usage: capture_index_lists.py --lake data/lake [--only DATASET ...]
Sequential with a pause between requests. A refusal (403, 429) stops the run, as `capture_current_lists.py` does; a 404 (NSE renamed a file) is reported and skipped.
A list already stored today is not fetched again, so repeating it is cheap."""

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from algo.data.index_members import FILES
from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BASE = "https://www.niftyindices.com/IndexConstituent/"
ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--only", nargs="*", default=[])
a = ap.parse_args()
lake, now = LocalLake(a.lake), datetime.now(UTC)
missing = []
for name, filename in FILES.items():
    if a.only and name not in a.only:
        continue
    if (a.lake / "raw/niftyindices" / name / f"dt={now.date()}").exists():
        print(f"{name:30} already stored today")
        continue
    time.sleep(2.5)
    try:
        req = urllib.request.Request(BASE + filename, headers={"User-Agent": UA})  # noqa: S310
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            data = bytes(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"{name:30} NOT FOUND ({filename})")
            missing.append(name)
            continue
        sys.exit(f"STOPPED at {filename}: HTTP {e.code} (not retrying)")
    if not data.lstrip(b"\xef\xbb\xbf").startswith(b"Company Name"):
        print(f"{name:30} not a constituent list (first bytes {data[:40]!r}): skipped")
        missing.append(name)
        continue
    m = lake.put("niftyindices", name, now.date(), data, url=BASE + filename, fetched_at=now)
    print(f"{name:30} v{m.version} {m.size:>8} bytes")
if missing:
    print(f"{len(missing)} not captured: {', '.join(missing)}")

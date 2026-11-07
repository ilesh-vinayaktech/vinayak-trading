"""Store today's official constituent lists and the equity-index methodology UNTOUCHED in the raw
lake (sha256), as independent end-state checks for each Nifty 200 component. Sequential, stops on
any refusal. usage: capture_current_lists.py --lake data/lake"""

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
BASE = "https://www.niftyindices.com"
FILES = {
    "nifty50_list": "/IndexConstituent/ind_nifty50list.csv",
    "niftynext50_list": "/IndexConstituent/ind_niftynext50list.csv",
    "niftymidcap100_list": "/IndexConstituent/ind_niftymidcap100list.csv",
    "nifty200_list": "/IndexConstituent/ind_nifty200list.csv",
    "equity_methodology": "/Methodology/Method_NIFTY_Equity_Indices.pdf",
}

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
a = ap.parse_args()
lake, now = LocalLake(a.lake), datetime.now(UTC)
for name, path in FILES.items():
    time.sleep(2.5)
    try:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})  # noqa: S310
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            data = bytes(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"STOPPED at {path}: HTTP {e.code} (not retrying)")
    m = lake.put("niftyindices", name, now.date(), data, url=BASE + path, fetched_at=now)
    print(f"{name:22} v{m.version} {m.size:>8} bytes sha256={m.checksum}")

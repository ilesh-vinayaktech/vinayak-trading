"""Fetch the official fee documents and store them UNTOUCHED in the versioned raw lake, with sha256.
Cost-schedule rates must cite one of these (url + sha256 + quote); nothing is hardcoded from memory.
usage: capture_cost_sources.py --lake data/lake"""

import argparse
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from algo.data.lake import LocalLake

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
ARCH = "https://nsearchives.nseindia.com/content/circulars"
NSE_STATIC = "https://www.nseindia.com/static/invest"
SOURCES = {
    "zerodha_charges": "https://zerodha.com/charges",
    "nse_stt_levies_page": f"{NSE_STATIC}/first-time-investor-sebi-turnover-fees-stt-other-levies",
    "nse_stamp_duty_page": f"{NSE_STATIC}/first-time-investor-stamp-duty-charges-taxes",
    "nse_FA73061": f"{ARCH}/FA73061.pdf",  # transaction charges, 27 Feb 2026, effective 1 Mar 2026
    "nse_FA56129": f"{ARCH}/FA56129.pdf",  # transaction charges, 24 Mar 2023, effective 1 Apr 2023
    "nse_FATAX73524": f"{ARCH}/FATAX73524.pdf",  # STT, 31 Mar 2026
    "nse_FATAX63809": f"{ARCH}/FATAX63809.pdf",  # STT, 9 Sep 2024
    "nse_FATAX56235": f"{ARCH}/FATAX56235.pdf",  # STT, 1 Apr 2023
    "nse_FATAX43604": f"{ARCH}/FATAX43604.pdf",  # STT, 19 Feb 2020
    "nse_FATAX41263": f"{ARCH}/FATAX41263.pdf",  # STT, 7 Jun 2019
    "nse_FATAX32385": f"{ARCH}/FATAX32385.pdf",  # STT, 16 May 2016
}

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
a = ap.parse_args()
lake, now = LocalLake(a.lake), datetime.now(UTC)
for name, url in SOURCES.items():
    req = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310
    with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310
        data = bytes(r.read())
    m = lake.put("costs", name, now.date(), data, url=url, fetched_at=now)
    print(f"{name:22} v{m.version} {m.size:>8} bytes sha256={m.checksum}")
    time.sleep(2)

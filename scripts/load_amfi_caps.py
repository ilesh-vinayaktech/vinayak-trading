# ruff: noqa: E501  (driver script)
"""Load AMFI's half-yearly market-cap rankings (large / mid / small / micro by rank) for every period AMFI publishes.

Reads AMFI's "Categorization of stocks" page, finds every Excel list on it (so a new half-year is picked up without code
changes), stores each raw file in the lake (source amfi, dataset avg_market_cap, dated by the list's period end), parses it
(algo.data.amfi_caps refuses a file that does not read exactly as expected) and loads it (algo.data.market_caps).
Re-running is safe: an unchanged file is the same lake version and the period is replaced, not duplicated.
The Jul-Dec 2017 list exists only as a PDF and is not read: before the first list is relied on (1 Aug 2018) a backtest
needs another way to size stocks, and must say so.
usage: load_amfi_caps.py [--db URL] [--lake data/lake]"""

import argparse
import hashlib
import os
import re
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from algo.data.amfi_caps import AmfiError, effective_from, parse_list
from algo.data.lake import LocalLake
from algo.data.market_caps import list_status, load_list

PAGE = "https://www.amfiindia.com/otherdata/categorisation-of-stocks"
LINK = re.compile(r"https?://[^\"' \\]*\.xlsx", re.I)
AGENT = {"User-Agent": "Mozilla/5.0 (research data loader)"}

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60) as r:
        return r.read()


page = get(PAGE).decode("utf-8", "replace")
links = sorted({u for u in LINK.findall(page) if "capitali" in u.lower()})
print(f"{len(links)} Excel lists on {PAGE}")
lake = LocalLake(a.lake)
with psycopg.connect(a.db, autocommit=True) as conn:
    for url in links:
        now = datetime.now(UTC)
        raw = get(url)
        try:
            cap_list = parse_list(raw)
        except AmfiError as e:
            print(f"  REFUSED {url}: {e}")
            continue
        lake.put("amfi", "avg_market_cap", cap_list.period_end, raw, url=url, fetched_at=now)
        r = load_list(conn, cap_list, url, hashlib.sha256(raw).hexdigest(), now)
        print(
            f"  {cap_list.period_end} (relied on from {effective_from(cap_list.period_end)}): {r.companies} companies, {r.matched} matched to our instruments"
        )
        time.sleep(1)  # be gentle with AMFI's site
    print(f"{len(list_status(conn))} lists loaded")

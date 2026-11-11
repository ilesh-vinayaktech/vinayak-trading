# ruff: noqa: E501
"""Pull NSE's holiday list into the live trading calendar (market_session) and say which special sessions still need hours.

Run it now and then (it only ever adds or refreshes upcoming closed days; sessions entered by hand are never touched).
The special sessions it lists (Muhurat and other starred days) are added with their start and end time on the portal's
Trading calendar page."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.lake import LocalLake
from algo.data.providers.nse_client import NseClient
from algo.live.calendar_sync import sync_holidays

HOLIDAYS = "https://www.nseindia.com/api/holiday-master?type=trading"
WARM = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

now = datetime.now(UTC)
client = NseClient()
client.warm(WARM)
raw = client.get(HOLIDAYS, accept="application/json")
LocalLake(a.lake).put("nse", "holiday_master", now.date(), raw, url=HOLIDAYS, fetched_at=now)
with psycopg.connect(a.db, autocommit=True) as conn:
    result = sync_holidays(
        conn, raw, today=now.astimezone(ZoneInfo("Asia/Kolkata")).date(), now=now
    )
print(f"{result.closed} upcoming closed days in the calendar")
for d in result.needs_times:
    print(f"needs its hours entered: {d:%a %d %b %Y}")

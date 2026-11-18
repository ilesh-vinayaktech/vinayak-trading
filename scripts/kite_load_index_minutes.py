# ruff: noqa: E501
"""Fill the 1-minute index bars (Nifty 50, Sensex, India VIX, ...) from Kite's own candles: today so far by default, or from a date.
usage: kite_load_index_minutes.py [--db URL] [--from YYYY-MM-DD]
Needs the portal's system data feed connected today (`set -a; . ./.env; set +a`). Minutes already stored (by the live feed or an earlier run) are kept. Safe to repeat."""

import argparse
import os
import sys
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import psycopg

from algo.core.clock import SystemClock
from algo.data.providers.kite import KiteClient
from algo.data.providers.kite_session import urllib_http
from algo.live.index_store import index_tokens, load_kite_minutes
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed_credentials

IST = ZoneInfo("Asia/Kolkata")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", type=date.fromisoformat)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = SystemClock().now()
with psycopg.connect(a.db, autocommit=True) as conn:
    creds = system_feed_credentials(conn, KeyRing.from_env(os.environ), now=now)
    if creds is None:
        sys.exit("no connected Kite system feed: connect on the portal's Kite page first")
    day = a.start or now.astimezone(IST).date()
    names = index_tokens(conn)
    start = datetime.combine(day, time(9, 0), IST)
    n = load_kite_minutes(
        conn, KiteClient(creds[0], creds[1], urllib_http, retries=3), names, start, now, now
    )
    print(f"{len(names)} indices, {n} new minutes from {start:%Y-%m-%d %H:%M} IST")

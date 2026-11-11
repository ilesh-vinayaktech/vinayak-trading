# ruff: noqa: E501
"""Run the live market-data service: Kite WebSocket -> 1-minute bars in live_bar_1m, status in feed_status.

Needs the portal's system data feed connected today (Kite page -> "Use my connection as the data feed") plus
ALGO_DB_URL and ALGO_VAULT_KEYS (`set -a; . ./.env; set +a`). Stops by itself at --until (IST, default 15:35),
on Ctrl-C / SIGTERM, or when Kite refuses the login (exit code 2: connect to Zerodha again and restart).
--record N saves the first N raw frames to data/logs/ticks_sample_<date>.bin (4-byte length + 8-byte epoch ms + frame),
so the parser can be checked against what Kite really sent."""

from __future__ import annotations

import argparse
import asyncio
import functools
import os
import signal
import struct
import sys
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.core.clock import SystemClock
from algo.live.bar_store import token_map
from algo.live.feed import Feed
from algo.live.kite_socket import connect
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed_credentials

IST = ZoneInfo("Asia/Kolkata")

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--until", default="15:35", help="HH:MM IST to stop at")
ap.add_argument("--mode", default="full", choices=["ltp", "quote", "full"])
ap.add_argument(
    "--record", type=int, default=0, help="save the first N raw frames for parser checks"
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

clock = SystemClock()
now = clock.now()
hh, mm = (int(x) for x in a.until.split(":"))
until = datetime.combine(now.astimezone(IST).date(), time(hh, mm), IST).astimezone(UTC)
with psycopg.connect(a.db, autocommit=True) as conn:
    creds = system_feed_credentials(conn, KeyRing.from_env(os.environ), now=now)
    if creds is None:
        sys.exit(
            "no connected system feed: connect on the portal's Kite page and enable the data feed"
        )
    ids = token_map(conn)
    if not ids:
        sys.exit(
            "no instruments mapped to Kite tokens: run scripts/kite_load_minutes.py once to map them"
        )
    api_key, access_token = creds
    kept: list[bytes] = []

    def sink(data: bytes, when: datetime) -> None:
        if len(kept) < a.record:
            kept.append(struct.pack(">IQ", len(data), int(when.timestamp() * 1000)) + data)

    feed = Feed(
        functools.partial(connect, api_key, access_token),
        conn,
        ids,
        clock,
        mode=a.mode,
        until=until,
        frame_sink=sink if a.record else None,
    )

    async def main() -> str:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, feed.stop)
        print(f"feeding {len(ids)} instruments until {until.astimezone(IST):%H:%M} IST", flush=True)
        return await feed.run()

    state = asyncio.run(main())
    if kept:
        out = Path("data/logs") / f"ticks_sample_{now.astimezone(IST):%Y%m%d}.bin"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"".join(kept))
        print(f"saved {len(kept)} raw frames to {out}")
    print(f"{state}: {feed.ticks} ticks, {feed.bars} bars, {feed.bad_frames} bad frames")
    sys.exit(2 if state == "TOKEN_EXPIRED" else 0)

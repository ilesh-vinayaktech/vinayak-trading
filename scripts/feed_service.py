# ruff: noqa: E501
"""Run the live market-data service: Kite WebSocket -> 1-minute bars in live_bar_1m, status in feed_status.

Needs the portal's system data feed connected today (Kite page -> "Use my connection as the data feed") plus
ALGO_DB_URL and ALGO_VAULT_KEYS (`set -a; . ./.env; set +a`). Follows the trading calendar (market_session; regular Mon-Fri 09:15-15:30 IST plus any special sessions added on the
portal): idle on a closed day, connects 15 minutes before the first window, stops 5 minutes after the last,
on Ctrl-C / SIGTERM, or (without --wait) when there is no valid Kite login (exit code 2).
With --wait it keeps checking every 30 s, so it can start before you connect and carries on after a mid-day token refusal.
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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.core.clock import SystemClock
from algo.data.lake import LocalLake
from algo.data.providers.kite import KiteClient, KiteError
from algo.data.providers.kite_session import urllib_http
from algo.live.bar_store import save_status, token_map
from algo.live.bars import BarBuilder
from algo.live.feed import Feed
from algo.live.instrument_refresh import RefreshError, last_refresh, refresh
from algo.live.kite_socket import connect
from algo.live.market_calendar import windows_for
from algo.portal.crypto import KeyRing
from algo.portal.kite_vault import system_feed_credentials

IST = ZoneInfo("Asia/Kolkata")

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--wait",
    action="store_true",
    help="wait (until the session ends) for the Zerodha connection instead of exiting",
)
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--mode", default="full", choices=["ltp", "quote", "full"])
ap.add_argument(
    "--record", type=int, default=0, help="save the first N raw frames for parser checks"
)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

clock = SystemClock()
now = clock.now()
ring = KeyRing.from_env(os.environ)
kept: list[bytes] = []


def sink(data: bytes, when: datetime) -> None:
    if len(kept) < a.record:
        kept.append(struct.pack(">IQ", len(data), int(when.timestamp() * 1000)) + data)


async def main(conn: psycopg.Connection) -> str:
    today = clock.now().astimezone(IST).date()
    windows = windows_for(conn, today)
    if not windows:
        print(f"no trading session on {today}: nothing to do", flush=True)
        return "STOPPED"
    open_at, until = windows[0][0] - timedelta(minutes=15), windows[-1][1] + timedelta(minutes=5)
    print(
        f"{today}: "
        + ", ".join(f"{s.astimezone(IST):%H:%M}-{e.astimezone(IST):%H:%M}" for s, e in windows)
        + " IST",
        flush=True,
    )
    stopping = False
    current: list[Feed] = []

    def stop() -> None:
        nonlocal stopping
        stopping = True
        for f in current:
            f.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    state = "STOPPED"
    while not stopping and clock.now() < open_at:
        await asyncio.sleep(30)  # an evening session: stay idle until shortly before it
    while not stopping and clock.now() < until:
        creds = system_feed_credentials(conn, ring, now=clock.now())
        if creds is None:
            if not a.wait:
                print(
                    "no connected system feed: connect on the portal's Kite page and enable the data feed"
                )
                return "TOKEN_EXPIRED"
            save_status(
                conn,
                "STOPPED",
                "waiting for you to connect to Zerodha on the Kite page",
                subscribed=len(token_map(conn)),
                last_tick_at=None,
                last_bar_at=None,
                ticks=0,
                bars=0,
                bad_frames=0,
                late_ticks=0,
                now=clock.now(),
            )
            await asyncio.sleep(30)
            continue
        if last_refresh(conn) != clock.now().astimezone(IST).date():
            # the first connection of the day: bring the Kite instrument list (and our token mapping) up to date
            try:
                r = refresh(
                    conn,
                    KiteClient(creds[0], creds[1], urllib_http, retries=3),
                    LocalLake(a.lake),
                    a.lake,
                    now=clock.now(),
                )
                print(
                    f"instrument dump: {r.total_rows} instruments, {r.mapped} mapped; added {r.added}; dropped {r.dropped}; token changes {r.token_changes}; unmatched {len(r.unmatched)}",
                    flush=True,
                )
            except (KiteError, RefreshError, OSError) as e:
                print(
                    f"instrument refresh failed ({e}); continuing with the existing mapping",
                    flush=True,
                )
        ids = token_map(conn)
        if not ids:
            sys.exit(
                "no instruments mapped to Kite tokens: run scripts/kite_load_minutes.py once to map them"
            )
        feed = Feed(
            functools.partial(connect, *creds),
            conn,
            ids,
            clock,
            mode=a.mode,
            until=until,
            builder=BarBuilder(windows=windows),
            frame_sink=sink if a.record else None,
        )
        current[:] = [feed]
        print(f"feeding {len(ids)} instruments until {until.astimezone(IST):%H:%M} IST", flush=True)
        state = await feed.run()
        print(
            f"{state}: {feed.ticks} ticks, {feed.bars} bars, {feed.bad_frames} bad frames",
            flush=True,
        )
        if state == "TOKEN_EXPIRED" and a.wait:
            await asyncio.sleep(30)  # Kite refused the login: wait for a fresh connection
            continue
        break
    return state


with psycopg.connect(a.db, autocommit=True) as conn:
    result = asyncio.run(main(conn))
if kept:
    out = Path("data/logs") / f"ticks_sample_{now.astimezone(IST):%Y%m%d}.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"".join(kept))
    print(f"saved {len(kept)} raw frames to {out}")
sys.exit(2 if result == "TOKEN_EXPIRED" else 0)

# ruff: noqa: E501  (driver script)
"""Load Kite DAILY candles (the full day's volume, unlike the minutes) for every mapped Nifty 500 instrument into bar_1d
(source 'kite'). Needs a live session (scripts/kite_login.py) and the Kite instrument mapping that kite_load_minutes.py
made. Resumable; the request spacing is global (default 2 s, so it can run next to the minute load without passing Kite's
3 requests/second limit). Stops cleanly when the session expires (exit 3).
usage: kite_load_days.py --db URL [--from 2016-01-01] [--to TODAY] [--symbols A,B] [--limit N] [--interval 2.0] [--workers 2]"""

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.kite_ingest import load_days
from algo.data.lake import LocalLake
from algo.data.providers.kite import KiteClient, KiteTokenExpired
from algo.data.providers.kite_session import load_env, load_token, urllib_http

IST = ZoneInfo("Asia/Kolkata")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2016, 1, 1))
ap.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
ap.add_argument("--symbols", default="")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
ap.add_argument("--interval", type=float, default=2.0)
ap.add_argument("--workers", type=int, default=2)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
env, tok = load_env(a.env), load_token(a.token_file, now)
if (
    tok is None
):  # no token file: use the connected data feed from the portal (stored encrypted in the database)
    from algo.portal.crypto import KeyRing
    from algo.portal.kite_vault import system_feed_credentials

    with psycopg.connect(a.db) as _c:
        _feed = system_feed_credentials(_c, KeyRing.from_env(os.environ), now=now)
    if _feed is not None:
        env["ZERODHA_API_KEY"], tok = _feed[0], (_feed[1], "portal feed")
if tok is None:
    sys.exit(
        "no valid Kite session: connect on the portal (data feed on) or run scripts/kite_login.py"
    )
client = KiteClient(env["ZERODHA_API_KEY"], tok[0], urllib_http, min_interval=a.interval, retries=6)
end = a.end or now.astimezone(IST).date()
lake = LocalLake(a.lake)
with psycopg.connect(a.db, autocommit=True) as conn:
    work = conn.execute(
        "SELECT instrument_token, tradingsymbol, instrument_id FROM kite_instrument WHERE instrument_id IS NOT NULL ORDER BY tradingsymbol"
    ).fetchall()
if a.symbols:
    work = [w for w in work if w[1] in set(a.symbols.split(","))]
work = work[: a.limit or None]
stop, lock, total, done = threading.Event(), threading.Lock(), 0, 0
t0 = time.monotonic()


def one(token: int, symbol: str, iid: int):
    if stop.is_set():
        return None
    with psycopg.connect(a.db, autocommit=True) as c:
        return symbol, load_days(c, client, token, iid, a.start, end, now, lake=lake)


try:
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(one, *w) for w in work]):
            try:
                out = f.result()
            except KiteTokenExpired:
                stop.set()
                raise
            if out is None:
                continue
            symbol, r = out
            with lock:
                done += 1
                total += r.rows
                print(
                    f"{done}/{len(work)} {symbol}: windows loaded {r.loaded} empty {r.empty} skipped {r.skipped} failed {r.failed} rows {r.rows} (total {total:,}, {time.monotonic() - t0:.0f}s)",
                    flush=True,
                )
except KiteTokenExpired:
    print(
        "STOPPED: the Kite session expired. Run scripts/kite_login.py and re-run: it resumes.",
        flush=True,
    )
    sys.exit(3)
print(f"DONE rows loaded this run: {total:,}", flush=True)

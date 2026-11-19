# ruff: noqa: E501
"""One-off history for the index charts: Kite one-minute candles of every index the live feed follows, into index_bar_1m (source 'kite').
usage: load_index_minutes.py [--db URL] [--days 180] [--symbols A,B]
The live feed stores minutes only from the day it first followed an index; this fills the days before. A minute already stored is left alone (the first writer wins), so it is safe to repeat
and never overwrites the feed. Needs a valid Kite session (scripts/kite_token_from_portal.py). Kite serves minute candles in windows of at most 60 days."""

import argparse
import os
import sys
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.providers.kite import KiteClient, KiteTokenExpired, windows
from algo.data.providers.kite_session import load_env, load_token, urllib_http
from algo.live.bars import LiveBar
from algo.live.index_store import index_tokens, save_index_bars
from algo.live.market_calendar import IST

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--days", type=int, default=180)
ap.add_argument("--symbols", default="")
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
env, tok = load_env(a.env), load_token(a.token_file, now)
if tok is None:
    sys.exit("no valid Kite session: run scripts/kite_token_from_portal.py")
client = KiteClient(env["ZERODHA_API_KEY"], tok[0], urllib_http, min_interval=0.4, retries=6)
end, start = now.astimezone(IST).date(), now.astimezone(IST).date() - timedelta(days=a.days)
want = set(a.symbols.split(",")) if a.symbols else None
total = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    names = {
        t: ex_sym for t, ex_sym in index_tokens(conn).items() if want is None or ex_sym[1] in want
    }
    for token, (exchange, symbol) in names.items():
        got = 0
        try:
            for ws, we in windows(start, end, 60):
                candles = client.historical(
                    token,
                    "minute",
                    datetime.combine(ws, time(0), IST),
                    datetime.combine(we, time(23, 59), IST),
                )
                bars = [
                    LiveBar(
                        token,
                        c.ts,
                        Decimal(str(c.open)),
                        Decimal(str(c.high)),
                        Decimal(str(c.low)),
                        Decimal(str(c.close)),
                        0,
                        0,
                        False,
                    )
                    for c in candles
                ]
                got += save_index_bars(conn, bars, {token: (exchange, symbol)}, now, source="kite")
        except KiteTokenExpired:
            sys.exit("STOPPED: Kite session expired; re-run (safe)")
        total += got
        print(f"{exchange} {symbol}: {got} new minutes (total {total:,})", flush=True)
print(f"DONE {len(names)} indexes, {total:,} minutes")

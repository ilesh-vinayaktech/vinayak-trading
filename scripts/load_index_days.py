# ruff: noqa: E501
"""Load Kite DAILY candles for every NSE/BSE index into index_bar_1d (trend setup). Needs a live session
(scripts/kite_token_from_portal.py). Re-runnable: upserts. usage: load_index_days.py --db URL [--from 1990-01-01] [--to TODAY] [--symbols A,B]"""

import argparse
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.index_daily import index_rows, load_index_days
from algo.data.providers.kite import KiteClient, KiteTokenExpired
from algo.data.providers.kite_session import load_env, load_token, urllib_http

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date(1990, 1, 1))
ap.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
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
raw: list[bytes] = []
client.instruments(None, raw_sink=raw.append)
rows = index_rows(raw[0])
if a.symbols:
    rows = [r for r in rows if r[2] in set(a.symbols.split(","))]
end = a.end or now.date()
total = 0
with psycopg.connect(a.db, autocommit=True) as conn:
    for r in rows:
        try:
            res = load_index_days(conn, client, [r], a.start, end, now)
        except KiteTokenExpired:
            sys.exit("STOPPED: Kite session expired; re-run (upserts, safe)")
        total += res.rows
        print(
            f"{r[1]} {r[2]}: {res.rows} rows{' (EMPTY)' if res.empty else ''} (total {total:,})",
            flush=True,
        )
print(f"DONE {len(rows)} indexes, {total:,} rows")

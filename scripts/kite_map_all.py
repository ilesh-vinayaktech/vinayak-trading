# ruff: noqa: E501  (driver script)
"""Map every active NSE equity in our instrument master to its Kite token (kite_instrument), so the daily and minute loaders
can download all of them, not only the Nifty 500. New rows are stored inactive: the live feed keeps following only the stocks
it already follows. Needs a live Kite session (scripts/kite_token_from_portal.py). Prints what could not be matched.
usage: kite_map_all.py [--db URL]"""

import argparse
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.kite_ingest import map_universe, master_universe, upsert_kite_instruments
from algo.data.lake import LocalLake
from algo.data.providers.kite import KiteClient
from algo.data.providers.kite_session import load_env, load_token, urllib_http

IST = ZoneInfo("Asia/Kolkata")
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
env, tok = load_env(a.env), load_token(a.token_file, now)
if tok is None:
    sys.exit("no valid Kite session: run scripts/kite_token_from_portal.py first")
client = KiteClient(env["ZERODHA_API_KEY"], tok[0], urllib_http, retries=3)
with psycopg.connect(a.db, autocommit=True) as conn:
    listing: list[bytes] = []
    instruments = client.instruments("NSE", raw_sink=listing.append)
    LocalLake(a.lake).put(
        "kite",
        "instruments_NSE",
        now.astimezone(IST).date(),
        listing[0],
        url="instruments/NSE",
        fetched_at=now,
    )
    universe = master_universe(conn)
    mapping = map_universe(conn, instruments, universe)
    upsert_kite_instruments(conn, mapping.mapped, now, active=False)
    why = Counter(reason for _, reason in mapping.unmatched)
    print(
        f"{len(universe)} equities in our master: mapped {len(mapping.mapped)}, unmatched {len(mapping.unmatched)} {dict(why)}"
    )
    for symbol, reason in mapping.unmatched[:15]:
        print(f"  {symbol}: {reason}")
    total, active = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE active) FROM kite_instrument"
    ).fetchone()
    print(f"kite_instrument now holds {total} stocks, {active} followed by the live feed")

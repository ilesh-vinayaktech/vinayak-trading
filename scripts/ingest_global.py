# ruff: noqa: E501
"""Global closes for the morning forecast into global_daily.
usage: ingest_global.py {yahoo,gift,all} [--db URL] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
  yahoo: S&P 500, Nasdaq and the US VIX daily closes (Yahoo Finance; default the last 10 days, `--from 2016-01-01` backfills in one request each).
  gift:  GIFT Nifty as at 08:45 IST each day from Kite minute candles (needs a valid Kite session; default the last 10 days; Kite keeps about two years of minutes).
Safe to repeat. Exit 1 when a source refuses or a payload is not understood (the job runner alerts)."""

import argparse
import csv
import io
import os
import sys
import urllib.request
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import psycopg

from algo.data import global_markets as g
from algo.data.providers.kite import KiteClient, KiteTokenExpired, windows
from algo.data.providers.kite_session import load_env, load_token, urllib_http

ap = argparse.ArgumentParser()
ap.add_argument("stage", choices=["yahoo", "gift", "all"])
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--from", dest="start", type=date.fromisoformat)
ap.add_argument("--to", dest="end", type=date.fromisoformat)
ap.add_argument("--env", type=Path, default=Path(".env"))
ap.add_argument("--token-file", type=Path, default=Path("data/secrets/kite_token.json"))
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
end = a.end or now.date()
start = a.start or end - timedelta(days=10)
with psycopg.connect(a.db, autocommit=True) as conn:
    if a.stage in ("yahoo", "all"):
        for name, symbol in g.YAHOO.items():
            req = urllib.request.Request(
                g.yahoo_url(symbol, start, end), headers={"User-Agent": "Mozilla/5.0"}
            )  # noqa: S310
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                rows = g.parse_yahoo(r.read())
            print(
                f"{name}: {g.store(conn, name, rows, 'yahoo', now)} days ({rows[0][0] if rows else '-'} to {rows[-1][0] if rows else '-'})"
            )
    if a.stage in ("gift", "all"):
        env, tok = load_env(a.env), load_token(a.token_file, now)
        if tok is None:
            sys.exit("no valid Kite session: run scripts/kite_token_from_portal.py")
        client = KiteClient(
            env["ZERODHA_API_KEY"], tok[0], urllib_http, min_interval=0.4, retries=6
        )
        raw: list[bytes] = []
        client.instruments(None, raw_sink=raw.append)
        token = next(
            int(r["instrument_token"])
            for r in csv.DictReader(io.StringIO(raw[0].decode()))
            if r["exchange"] == "NSEIX" and r["tradingsymbol"] == "GIFT NIFTY"
        )
        total = 0
        try:
            for ws, we in windows(start, end, 60):
                candles = client.historical(
                    token,
                    "minute",
                    datetime.combine(ws, time(8, 40), g.IST),
                    datetime.combine(we, time(8, 50), g.IST),
                )
                total += g.store(
                    conn,
                    g.GIFT,
                    g.gift_reading([(c.ts, float(c.close)) for c in candles]),
                    "kite",
                    now,
                )
        except KiteTokenExpired:
            sys.exit("Kite session expired: run scripts/kite_token_from_portal.py")
        print(f"GIFT Nifty 08:45: {total} days")

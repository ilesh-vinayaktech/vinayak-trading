"""Load the stored current constituent lists as dated snapshots (Nifty 50, Next 50, Midcap 100,
Nifty 200) and check that the three components exactly make up the Nifty 200 list.
usage: load_current_lists.py --lake data/lake --db postgresql://..."""

import argparse
import csv
import io
import os
from datetime import date
from pathlib import Path

import psycopg

from algo.data.instrument_sync import load_index_snapshot
from algo.data.lake import LocalLake
from algo.data.store.migrate import migrate

LISTS = {
    "NIFTY50": "nifty50_list",
    "NIFTYNEXT50": "niftynext50_list",
    "NIFTYMIDCAP100": "niftymidcap100_list",
    "NIFTY200": "nifty200_list",
}

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake = LocalLake(a.lake)
symbols: dict[str, list[str]] = {}
as_of = date.min
for index_id, dataset in LISTS.items():
    m = lake.latest("niftyindices", dataset)
    if m is None:
        raise SystemExit(f"{dataset} not captured: run capture_current_lists.py")
    as_of = date.fromisoformat(m.partition)
    rows = csv.DictReader(io.StringIO(lake.get(m).decode("utf-8-sig")))
    symbols[index_id] = [r["Symbol"].strip() for r in rows]
union = set(symbols["NIFTY50"]) | set(symbols["NIFTYNEXT50"]) | set(symbols["NIFTYMIDCAP100"])
print(f"lists as of {as_of}: " + ", ".join(f"{k}={len(v)}" for k, v in symbols.items()))
extra, short = sorted(union - set(symbols["NIFTY200"])), sorted(set(symbols["NIFTY200"]) - union)
print(f"components vs Nifty 200 list: only in components {extra}, only in Nifty 200 {short}")
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for index_id, syms in symbols.items():
        stored, unknown = load_index_snapshot(conn, index_id, as_of, syms)
        print(f"{index_id:15} stored {stored:>3}  unknown symbols: {unknown}")

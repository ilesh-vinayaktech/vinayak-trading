# ruff: noqa: E501  (report/driver script: long usage and format lines)
"""Load quarterly financial results (NSE XBRL) for the Nifty 500 into fundamental_filing / fundamental_fact.

Resumable: re-run to continue; filings already stored are not downloaded again. Polite: one request per --interval
seconds through the repo's NseClient (cookies refreshed every 40 symbols), and a 401/403 stops the whole run.
Raw listings and XBRL files are kept untouched in the lake. Nothing outside the fundamental_* tables is written.
usage: ingest_fundamentals.py --db URL [--lake data/lake] [--since 2016-04-01] [--basis CONSOLIDATED|STANDALONE|BOTH]
       [--symbols A,B] [--offset N] [--limit N] [--interval 1.0]"""

import argparse
import csv
import io
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.fundamentals_ingest import Blocked, ingest_symbol
from algo.data.lake import LocalLake
from algo.data.providers.nse_client import NseClient
from algo.data.store.migrate import migrate

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--since", type=date.fromisoformat, default=date(2016, 4, 1))
ap.add_argument("--basis", choices=("CONSOLIDATED", "STANDALONE", "BOTH"), default="BOTH")
ap.add_argument("--symbols", default="")
ap.add_argument("--offset", type=int, default=0)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--interval", type=float, default=1.0)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
WARM = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"

if a.symbols:
    universe = [s.strip() for s in a.symbols.split(",") if s.strip()]
else:
    latest = sorted((a.lake / "raw/niftyindices/nifty500_list").glob("dt=*/v*.bin"))[-1]
    universe = [
        r["Symbol"] for r in csv.DictReader(io.StringIO(latest.read_bytes().decode("utf-8-sig")))
    ]
universe = universe[a.offset :][: a.limit or None]
bases = ("CONSOLIDATED", "STANDALONE") if a.basis == "BOTH" else (a.basis,)
client, lake = NseClient(min_interval=a.interval), LocalLake(a.lake)
client.warm(WARM)
totals = {"listed": 0, "stored": 0, "already": 0}
gaps: dict[str, int] = {}
failed: list[str] = []
t0 = time.monotonic()
with psycopg.connect(a.db, autocommit=True) as conn:
    migrate(conn)
    for i, sym in enumerate(universe, 1):
        if i % 40 == 0:
            client.warm(WARM)
        try:
            r = ingest_symbol(
                conn, lake, client.get, sym, datetime.now(UTC), since=a.since, bases=bases
            )
        except Blocked as e:
            print(f"STOPPED at {sym}: {e}", flush=True)
            sys.exit(2)
        except Exception as e:  # one company's failure must not end the run
            failed.append(sym)
            print(f"[{i}/{len(universe)}] {sym}: FAILED {e!r}"[:200], flush=True)
            continue
        for k in totals:
            totals[k] += getattr(r, k)
        for k, v in r.noted.items():
            gaps[k] = gaps.get(k, 0) + v
        print(
            f"[{i}/{len(universe)}] {sym}: listed {r.listed} stored {r.stored} already {r.already} gaps {r.noted} ({time.monotonic() - t0:.0f}s)",
            flush=True,
        )
print(f"DONE {totals} gaps {gaps} failed symbols {failed}", flush=True)

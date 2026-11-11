# ruff: noqa: E501  (driver script: long usage and progress lines)
"""Load 1-minute Kite candles for the Nifty 500 into bar_1m (adjusted_through = the fetch date).

Run `scripts/kite_login.py` first (the token expires at 6 AM IST). Resumable: re-run to continue; finished windows are
not asked again. Works in calendar-year passes, NEWEST FIRST (so the most recent years are complete first), pausing the
automatic compression job during the load and compressing each finished pass. Stops cleanly when the session expires and
refuses to continue below --min-free-gb of free disk.
usage: kite_load_minutes.py --db URL [--from 2016-01-01] [--to TODAY] [--symbols A,B] [--limit N] [--min-free-gb 15] [--interval 0.4]"""

import argparse
import csv
import io
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from algo.data.kite_ingest import load_minutes, map_universe, upsert_kite_instruments
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
ap.add_argument("--min-free-gb", type=float, default=15.0)
ap.add_argument("--interval", type=float, default=0.4)
ap.add_argument(
    "--workers",
    type=int,
    default=3,
    help="parallel instruments; the request spacing is global, so this does not exceed Kite's limit",
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
env, tok = load_env(a.env), load_token(a.token_file, now)
if tok is None:
    sys.exit("no valid Kite session: run scripts/kite_login.py first")
client = KiteClient(env["ZERODHA_API_KEY"], tok[0], urllib_http, min_interval=a.interval)
end = a.end or now.astimezone().date()

latest = sorted((a.lake / "raw/niftyindices/nifty500_list").glob("dt=*/v*.bin"))[-1]
universe = [
    (r["Symbol"], r["ISIN Code"], r["Series"])
    for r in csv.DictReader(io.StringIO(latest.read_bytes().decode("utf-8-sig")))
]
if a.symbols:
    want = {s.strip() for s in a.symbols.split(",")}
    universe = [u for u in universe if u[0] in want]
with psycopg.connect(a.db, autocommit=True) as conn:
    lake = LocalLake(a.lake)
    listing: list[bytes] = []
    instruments = client.instruments("NSE", raw_sink=listing.append)
    lake.put(
        "kite",
        "instruments_NSE",
        now.astimezone(IST).date(),
        listing[0],
        url="instruments/NSE",
        fetched_at=now,
    )  # the full dump, every field
    mapping = map_universe(conn, instruments, universe)
    upsert_kite_instruments(conn, mapping.mapped, now)
    print(
        f"universe {len(universe)}: mapped {len(mapping.mapped)}, unmatched {mapping.unmatched}",
        flush=True,
    )
    work = sorted(mapping.mapped, key=lambda m: m[0].tradingsymbol)[: a.limit or None]
    passes = [
        (max(date(y, 1, 1), a.start), min(date(y, 12, 31), end))
        for y in range(end.year, a.start.year - 1, -1)
    ]
    hyper = conn.execute("SELECT 1 FROM pg_proc WHERE proname='show_chunks'").fetchone() is not None
    job = (
        conn.execute(
            "SELECT job_id FROM timescaledb_information.jobs WHERE hypertable_name='bar_1m' AND proc_name='policy_compression'"
        ).fetchone()
        if hyper
        else None
    )
    if job:
        conn.execute(
            "SELECT alter_job(%s, scheduled => false)", (job[0],)
        )  # no compression mid-load: inserting into compressed chunks is slow
    total, t0, lock = 0, time.monotonic(), threading.Lock()
    stop = threading.Event()

    def one(
        k, iid, ps, pe
    ):  # each worker has its own connection; the client spaces requests globally
        if stop.is_set():
            return None
        with psycopg.connect(a.db, autocommit=True) as wconn:
            return k, load_minutes(wconn, client, k.instrument_token, iid, ps, pe, now, lake=lake)

    try:
        for ps, pe in passes:
            free = shutil.disk_usage(a.lake).free / 1e9
            if free < a.min_free_gb:
                sys.exit(
                    f"STOPPED: only {free:.1f} GB free (< {a.min_free_gb}); nothing is lost, free space and re-run"
                )
            done = 0
            with ThreadPoolExecutor(max_workers=a.workers) as pool:
                futures = [pool.submit(one, k, iid, ps, pe) for k, iid in work]
                try:
                    for f in as_completed(futures):
                        out = f.result()
                        if out is None:
                            continue
                        k, r = out
                        done += 1
                        with lock:
                            total += r.rows
                            print(
                                f"[{ps.year}] {done}/{len(work)} {k.tradingsymbol}: windows loaded {r.loaded} empty {r.empty} skipped {r.skipped} failed {r.failed} rows {r.rows} (total {total:,}, {time.monotonic() - t0:.0f}s, {free:.0f} GB free)",
                                flush=True,
                            )
                except KiteTokenExpired:
                    stop.set()
                    raise
            if hyper:
                n = conn.execute(
                    "SELECT count(compress_chunk(c, if_not_compressed => true)) FROM show_chunks('bar_1m', older_than => (%s::date - 7)::timestamptz) c",
                    (end,),
                ).fetchone()[0]
                print(
                    f"[{ps.year}] pass complete: compressed {n} chunks; bar_1m now {conn.execute('SELECT pg_size_pretty(hypertable_size(%s))', ('bar_1m',)).fetchone()[0]}",
                    flush=True,
                )
    except KiteTokenExpired:
        print(
            "STOPPED: the Kite session expired. Run scripts/kite_login.py and re-run: it resumes where it stopped.",
            flush=True,
        )
        sys.exit(3)
    finally:
        if job:
            conn.execute("SELECT alter_job(%s, scheduled => true)", (job[0],))
print(f"DONE rows loaded this run: {total:,}", flush=True)

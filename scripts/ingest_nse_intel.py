# ruff: noqa: E501
"""Poll NSE for bulk/block deals, FII/DII flows, insider trades and shareholding patterns, and print what is NEW.
Safe to run as often as you like (inserts skip what is stored). Raw responses go to the lake first.

usage: ingest_nse_intel.py {deals,deals-history,fiidii,insider,insider-legacy,shareholding,shareholding-history,split,all} [--from YYYY-MM-DD] [--to YYYY-MM-DD]
  deals / fiidii / shareholding: NSE publishes only the latest session (or quarter), so the daily poll is what builds history.
  insider: NSE's list from 2026-05-03 (one row per filing; each filing's file is then read for person, quantity, value), window default the last 7 days; `--from 2026-05-03 --limit 5000` backfills.
  insider-legacy: the old list up to 2026-05-02, for history in a new database (`--from 2025-01-01`, one request per month).
  deals-history: bulk and block deals for any period from NSE's report page (`--from 2016-01-01`, to today by default; one request per kind per 365 days).
  shareholding-history: every filing made in the window (`--from 2021-10-01`, one request per month): NSE's structured feed is complete only from the Sep-2021 quarter (a few dozen companies a quarter before that).
  split: reads the XBRL of filings not yet read (FII/DII/MF/retail %), newest first, `--limit` per run; `all` does not include it.
Exit 1 when NSE refuses or a payload changed shape (the job runner alerts)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

from algo.data import nse_intel as n
from algo.data.lake import LocalLake
from algo.data.providers.base import ParseError
from algo.data.providers.nse_client import NseClient, NseHttpError

ap = argparse.ArgumentParser()
ap.add_argument(
    "stage",
    choices=[
        "deals",
        "fiidii",
        "insider",
        "insider-legacy",
        "deals-history",
        "shareholding-history",
        "shareholding",
        "split",
        "all",
    ],
)
ap.add_argument(
    "--limit", type=int, default=300, help="split / insider: filings whose file is read per run"
)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--from", dest="start", type=date.fromisoformat)
ap.add_argument("--to", dest="end", type=date.fromisoformat)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")

now = datetime.now(UTC)
lake, client = LocalLake(a.lake), NseClient()
client.warm(n.WARM)
JSON = "application/json,*/*"


def fetch(dataset: str, url: str, accept: str = JSON) -> bytes:
    raw = client.get(url, accept=accept)
    lake.put("nse", dataset, now.date(), raw, url=url, fetched_at=now)
    return raw


def months(start: date, end: date):
    """Calendar-month windows covering start..end, so a long backfill is many small requests."""
    d = start
    while d <= end:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield d, min(end, nxt - timedelta(days=1))
        d = nxt


try:
    with psycopg.connect(a.db, autocommit=True) as conn:
        if a.stage in ("deals", "all"):
            for kind, url in (("bulk", n.BULK_URL), ("block", n.BLOCK_URL)):
                rows = n.parse_deals(fetch(f"{kind}_deals", url, "text/csv,*/*"), kind)
                print(
                    f"{kind} deals: {len(rows)} on the file, {n.store_deals(conn, rows, now)} new"
                )
        if a.stage == "deals-history":
            client.warm(n.DEALS_HISTORY_WARM)
            end = a.end or now.date()
            d = a.start or end - timedelta(days=365)
            while d <= end:
                e = min(end, d + timedelta(days=364))
                for kind in ("bulk", "block"):
                    rows = n.parse_deals(
                        fetch(
                            f"{kind}_deals_history",
                            n.DEALS_HISTORY_URL.format(kind=kind, start=d, end=e),
                            "text/csv,*/*",
                        ),
                        kind,
                    )
                    print(
                        f"{kind} deals {d} to {e}: {len(rows)} listed, {n.store_deals(conn, rows, now)} new",
                        flush=True,
                    )
                d = e + timedelta(days=1)
        if a.stage == "shareholding-history":
            for ms, me in months(a.start or date(2021, 10, 1), a.end or now.date()):
                raw = fetch(
                    "shareholding_history", n.SHAREHOLDING_HISTORY_URL.format(start=ms, end=me)
                )
                rows = n.parse_shareholding(raw, skip_undated=True)
                skipped = len(json.loads(raw)) - len(rows)
                new = n.store_shareholding(conn, rows, now)
                note = f", {skipped} without a period skipped" if skipped else ""
                print(
                    f"shareholding filed {ms} to {me}: {len(rows)} listed, {new} new{note}",
                    flush=True,
                )
        if a.stage in ("fiidii", "all"):
            rows = n.parse_fii_dii(fetch("fii_dii", n.FII_DII_URL))
            print(f"FII/DII: {len(rows)} on the file, {n.store_fii_dii(conn, rows, now)} new")
        if a.stage in ("insider", "all"):
            end = a.end or now.date()
            rows = n.parse_pit_index(
                fetch(
                    "insider_pit_index",
                    n.INSIDER_INDEX_URL.format(start=a.start or end - timedelta(days=7), end=end),
                )
            )
            new = n.store_pit_index(conn, rows, now)
            done = failed = 0
            for app_id, _sym, at, url in n.pending_pit_details(conn, a.limit):
                try:
                    trades = n.parse_pit_detail(app_id, client.get(url, accept="*/*"), at, url)
                    n.store_insider(conn, trades, now)
                    n.mark_pit_detail(conn, app_id, now)
                    done += 1
                except ParseError as e:  # unreadable: record why, do not retry it every hour
                    n.mark_pit_detail(conn, app_id, now, str(e))
                    failed += 1
                except NseHttpError as e:
                    if e.status in (401, 403):
                        raise
                    failed += 1  # left unread, tried again next run
            print(
                f"insider filings: {len(rows)} listed, {new} new; {done} files read, {failed} failed, {len(n.pending_pit_details(conn, 10**6))} waiting"
            )
        if (
            a.stage == "insider-legacy"
        ):  # the old list, which ends 2026-05-02: only for loading history into a new database
            end = a.end or date(2026, 5, 2)
            new = total = 0
            for s, e in months(a.start or end - timedelta(days=7), end):
                rows = n.parse_insider(fetch("insider_pit", n.INSIDER_URL.format(start=s, end=e)))
                total += len(rows)
                new += n.store_insider(conn, rows, now)
            print(f"insider trades (old list): {total} listed, {new} new")
        if a.stage in ("shareholding", "all"):
            rows = n.parse_shareholding(fetch("shareholding", n.SHAREHOLDING_URL))
            print(
                f"shareholding: {len(rows)} filings listed, {n.store_shareholding(conn, rows, now)} new"
            )
        if a.stage == "split":
            done = failed = 0
            for rid, url in n.pending_splits(conn, a.limit):
                try:
                    raw = client.get(
                        url.replace("nsearchives.nseindia.in", "nsearchives.nseindia.com"),
                        accept="*/*",
                    )
                    n.store_split(conn, rid, n.parse_shareholding_split(raw), now)
                    done += 1
                except (
                    ParseError
                ) as e:  # the file is unreadable: record why, do not retry it every night
                    n.store_split(conn, rid, None, now, str(e))
                    failed += 1
                except NseHttpError as e:
                    if e.status in (401, 403):
                        raise  # refused: stop, do not hammer
                    failed += 1  # 404 and the like: left unread, tried again next run
            print(
                f"shareholding split: {done} read, {failed} failed, {len(n.pending_splits(conn, 10**6))} still waiting"
            )
except Exception as e:  # noqa: BLE001  (any failure must reach the job runner as exit 1)
    print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)

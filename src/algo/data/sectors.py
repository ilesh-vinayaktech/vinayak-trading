# ruff: noqa: E501
"""Sector (industry group) of each stock, as dated data, and the peer median a ratio is judged against.

The sector comes from NSE's own index constituent lists (the `Industry` column of the Nifty 500 list); each loaded snapshot is a set of rows
effective from the snapshot's date, so a stock that changes sector keeps its history and a question about an earlier day gets the earlier answer.
Only stocks on the list have a sector; the others have none and no peer view."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

import psycopg

from algo.core.clock import require_utc
from algo.data.store.instruments import InstrumentRepo, NotFoundError


@dataclass(frozen=True)
class Peer:
    sector: str | None
    median: Decimal | None
    peers: int  # how many other stocks of the sector had a value


def parse(raw: bytes) -> list[tuple[str, str, str]]:
    """(symbol, isin, industry) for every row of an NSE list that names an industry."""
    out = []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        if (r.get("Industry") or "").strip():
            out.append((r["Symbol"].strip(), r["ISIN Code"].strip(), r["Industry"].strip()))
    return out


def load_snapshot(
    conn: psycopg.Connection, raw: bytes, effective: date, source_sha256: str, now: datetime
) -> tuple[int, list[str]]:
    """Store one list as of `effective`. Returns (rows stored, symbols with no instrument). A stock whose sector is unchanged since its latest row adds nothing."""
    now = require_utc(now)
    repo = InstrumentRepo(conn)
    stored, unmatched = 0, []
    for symbol, _isin, industry in parse(raw):
        try:
            iid = repo.resolve("nse", symbol, effective)
        except NotFoundError:
            unmatched.append(symbol)
            continue
        last = conn.execute(
            "SELECT sector FROM instrument_sector WHERE instrument_id=%s AND effective_from <= %s ORDER BY effective_from DESC LIMIT 1",
            (iid, effective),
        ).fetchone()
        if last is not None and last[0] == industry:
            continue
        stored += conn.execute(
            "INSERT INTO instrument_sector (instrument_id, sector, effective_from, source_sha256, ingested_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (iid, industry, effective, source_sha256, now),
        ).rowcount
    return stored, unmatched


def sectors_on(conn: psycopg.Connection, day: date) -> dict[int, str]:
    """The sector of every stock that has one, as known on `day`."""
    return {
        int(i): s
        for i, s in conn.execute(
            "SELECT DISTINCT ON (instrument_id) instrument_id, sector FROM instrument_sector WHERE effective_from <= %s ORDER BY instrument_id, effective_from DESC",
            (day,),
        )
    }


def peer_median(
    values: dict[int, Decimal | None], sector_of: dict[int, str], iid: int, *, min_peers: int = 1
) -> Peer:
    """Median of `values` over the OTHER stocks of iid's sector that have a value. No median below `min_peers` peers."""
    sector = sector_of.get(iid)
    if sector is None:
        return Peer(None, None, 0)
    peers = [
        v for i, v in values.items() if i != iid and v is not None and sector_of.get(i) == sector
    ]
    return Peer(sector, median(peers) if len(peers) >= min_peers else None, len(peers))


def relative(value: Decimal | None, peer: Peer) -> Decimal | None:
    """value / peer median (below 1 = cheaper than its sector for a ratio like P/E); None when either is missing or the median is zero."""
    if value is None or peer.median is None or peer.median == 0:
        return None
    return value / peer.median


def load_latest(
    conn: psycopg.Connection, lake_root: Path, now: datetime
) -> tuple[date, int, list[str]]:
    """Load the newest Nifty 500 list in the lake (raw/niftyindices/nifty500_list/dt=YYYY-MM-DD/) as of its date. Returns (date, rows stored, unmatched symbols)."""
    parts = sorted((lake_root / "raw/niftyindices/nifty500_list").glob("dt=*"))
    if not parts:
        raise FileNotFoundError("no nifty500_list snapshot in the lake")
    newest = parts[-1]
    files = sorted(newest.glob("v*.bin"))
    if not files:
        raise FileNotFoundError(f"{newest} holds no list file")
    raw = files[-1].read_bytes()
    day = date.fromisoformat(newest.name.removeprefix("dt="))
    stored, unmatched = load_snapshot(conn, raw, day, hashlib.sha256(raw).hexdigest(), now)
    return day, stored, unmatched

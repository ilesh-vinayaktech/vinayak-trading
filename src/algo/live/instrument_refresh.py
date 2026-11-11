# ruff: noqa: E501
"""The daily Kite instrument dump: fetch it, archive it, and bring our token mapping up to date.

The whole dump (every exchange, every field) is stored in the lake exactly as received. The universe is the latest Nifty 500
list (the superset of every index list we use); each member is mapped to its Kite token with the same rules as the history
loader (`map_universe`). The result says what changed since the last mapping: symbols newly mapped, symbols that dropped
out, tokens that changed, and the ones that could not be mapped and why. Tokens no longer in the mapping stay in
`kite_instrument` for history but become inactive, so the live feed only follows today's instruments. A failed fetch raises
before anything is touched, leaving yesterday's mapping in place."""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from algo.data.kite_ingest import map_universe, upsert_kite_instruments
from algo.data.lake import LocalLake
from algo.data.providers.kite import KiteInstrument

IST = ZoneInfo("Asia/Kolkata")


class InstrumentSource(Protocol):
    def instruments(
        self, exchange: str | None = None, *, raw_sink: Callable[[bytes], None] | None = None
    ) -> list[KiteInstrument]: ...


class RefreshError(Exception):
    pass


@dataclass(frozen=True)
class RefreshResult:
    day: date
    raw_sha256: str
    total_rows: int
    nse_equities: int
    mapped: int
    unmatched: list[tuple[str, str]]
    added: list[str]
    dropped: list[str]
    token_changes: list[tuple[str, int, int]]


def universe_rows(lake_root: Path, list_name: str) -> list[tuple[str, str, str]]:
    """(symbol, ISIN, series) of the newest list in the lake."""
    folders = sorted((lake_root / "raw/niftyindices" / list_name).glob("dt=*"))
    if not folders:
        raise RefreshError(f"no {list_name} in the lake")
    newest = sorted(folders[-1].glob("v*.bin"), key=lambda p: int(p.stem[1:]))[-1]
    rows = csv.DictReader(io.StringIO(newest.read_bytes().decode("utf-8-sig")))
    return [(r["Symbol"], r["ISIN Code"], r["Series"]) for r in rows]


def last_refresh(conn: psycopg.Connection) -> date | None:
    row = conn.execute("SELECT max(refresh_day) FROM kite_instrument_refresh").fetchone()
    assert row is not None
    last: date | None = row[0]
    return last


def refresh(
    conn: psycopg.Connection,
    client: InstrumentSource,
    lake: LocalLake,
    lake_root: Path,
    *,
    now: datetime,
    list_name: str = "nifty500_list",
) -> RefreshResult:
    day = now.astimezone(IST).date()
    raw: list[bytes] = []
    nse = client.instruments(None, raw_sink=raw.append)
    body = raw[0]
    lake.put("kite", "instruments", day, body, url="instruments", fetched_at=now)
    mapping = map_universe(conn, nse, universe_rows(lake_root, list_name))

    before = {
        int(iid): (int(token), sym)
        for token, sym, iid in conn.execute(
            "SELECT instrument_token, tradingsymbol, instrument_id FROM kite_instrument WHERE active AND instrument_id IS NOT NULL"
        )
    }
    after = {iid: (k.instrument_token, k.tradingsymbol) for k, iid in mapping.mapped}
    added = sorted(sym for iid, (_, sym) in after.items() if iid not in before)
    dropped = sorted(sym for iid, (_, sym) in before.items() if iid not in after)
    changes = sorted(
        (after[iid][1], before[iid][0], after[iid][0])
        for iid in after
        if iid in before and before[iid][0] != after[iid][0]
    )
    result = RefreshResult(
        day,
        hashlib.sha256(body).hexdigest(),
        len(body.splitlines()) - 1,
        len(nse),
        len(mapping.mapped),
        list(mapping.unmatched),
        added,
        dropped,
        changes,
    )
    with conn.transaction():
        upsert_kite_instruments(conn, mapping.mapped, now)
        conn.execute(
            "UPDATE kite_instrument SET active = (instrument_token = ANY(%s))",
            ([k.instrument_token for k, _ in mapping.mapped],),
        )
        conn.execute(
            "INSERT INTO kite_instrument_refresh (refresh_day, fetched_at, raw_sha256, total_rows, nse_equities, mapped, unmatched, added, dropped, token_changes)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (refresh_day) DO UPDATE SET fetched_at=EXCLUDED.fetched_at, raw_sha256=EXCLUDED.raw_sha256,"
            " total_rows=EXCLUDED.total_rows, nse_equities=EXCLUDED.nse_equities, mapped=EXCLUDED.mapped, unmatched=EXCLUDED.unmatched,"
            " added=EXCLUDED.added, dropped=EXCLUDED.dropped, token_changes=EXCLUDED.token_changes",
            (
                day,
                now,
                result.raw_sha256,
                result.total_rows,
                result.nse_equities,
                result.mapped,
                Jsonb(result.unmatched),
                Jsonb(added),
                Jsonb(dropped),
                Jsonb(changes),
            ),
        )
    return result

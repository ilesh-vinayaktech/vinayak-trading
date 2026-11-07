"""Historical (delisted) instruments, inferred ONLY from evidence we hold.

An instrument is created automatically when a symbol (a) was needed (it was a Nifty 50/Next 50/
Nifty 100/Midcap 100/Nifty 200 component per the parsed press releases), (b) traded in the daily
bhavcopy files we hold, (c) is absent from the security master, and (d) stopped appearing well
before the end of our data. Its delisting date is the day after its last trade seen; the basis is
recorded on the instrument. Symbols with no trading evidence (pre-2019-10 names, possible renames)
are NOT created: they are reported as needing evidence. Nothing here comes from memory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.core.calendar import nse
from algo.core.clock import require_utc
from algo.data.bars import SPECS
from algo.data.lake import LocalLake
from algo.data.providers.nse_bhavcopy import NseBhavcopy

STILL_TRADING_DAYS = 10  # last seen within this many days of the data end => not delisted

CREATE = "CREATE"
STILL_TRADING = "STILL_TRADING_NOT_IN_MASTER"
NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
SUCCESSOR = "SUCCESSOR_SUSPECTED"  # a similarly named instrument appears soon after: rename/merger?
ALIAS_GAP = "ALIAS_VALIDITY_GAP"  # an alias exists, but not at the dates it is needed


@dataclass(frozen=True)
class Candidate:
    symbol: str
    action: str
    first_evidence: date | None  # earliest date we have evidence the symbol existed
    last_traded: date | None  # last bhavcopy day it appeared
    needed_for: tuple[str, ...]  # components that cited it
    reason: str
    company: str = ""  # as printed in the press releases


def data_end(conn: psycopg.Connection) -> date:
    row = conn.execute(
        "SELECT max(partition) FROM partition_load WHERE status IN ('loaded','noop')"
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("no bhavcopy partitions loaded")
    return row[0]  # type: ignore[no-any-return]


def bhavcopy_presence(conn: psycopg.Connection) -> dict[str, tuple[date, date]]:
    """symbol -> (first, last) day it was in a loaded bhavcopy but unknown to the master."""
    return {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT s, min(partition), max(partition) FROM partition_load,"
            " jsonb_array_elements_text(detail->'unknown_symbols') s"
            " WHERE status='loaded' GROUP BY s"
        )
    }


def successors(conn: psycopg.Connection, company: str, last_traded: date) -> list[str]:
    """Instruments whose NAME starts with the same word as `company`, whose NSE alias begins within
    [30 days before, 120 days after] its last trade: a rename/merger candidate, not a delisting."""
    words = re.findall(r"[A-Za-z0-9]+", company.lower())
    if not words or len(words[0]) < 4:
        return []
    rows = conn.execute(
        "SELECT a.source_symbol FROM instrument_alias a JOIN instrument i USING (instrument_id)"
        " WHERE a.source='nse' AND lower(i.name) LIKE %s AND a.valid_from BETWEEN %s AND %s"
        " ORDER BY 1",
        (words[0] + "%", last_traded - timedelta(days=30), last_traded + timedelta(days=120)),
    ).fetchall()
    return [r[0] for r in rows]


def plan(conn: psycopg.Connection) -> list[Candidate]:
    end = data_end(conn)
    seen = bhavcopy_presence(conn)
    needed = conn.execute(
        "SELECT symbol, min(effective_from), array_agg(DISTINCT component),"
        " coalesce((array_agg(company) FILTER (WHERE company <> ''"
        " AND company NOT LIKE 'parent:%'))[1], '')"
        " FROM index_release_row"
        " WHERE component IS NOT NULL AND mapping_status = 'UNMAPPED_SYMBOL'"
        " GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    has_alias = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT source_symbol FROM instrument_alias WHERE source='nse'"
        )
    }
    out = []
    for symbol, first_release, comps, company in needed:
        first_ev = first_release
        if symbol in has_alias:  # same company under a symbol the master dates differently
            why = "alias exists but not at the needed dates: extend it, or a different company?"
            last_seen = seen[symbol][1] if symbol in seen else None
            out.append(Candidate(symbol, ALIAS_GAP, first_ev, last_seen, tuple(comps), why))
            continue
        if symbol in seen:
            first_ev = min(d for d in (first_release, seen[symbol][0]) if d)
            last = seen[symbol][1]
            if (end - last).days <= STILL_TRADING_DAYS:
                reason = "trades to the end of the data, not in the master"
                out.append(Candidate(symbol, STILL_TRADING, first_ev, last, tuple(comps), reason))
            else:
                succ = successors(conn, company, last)
                if succ:
                    why = f"similarly named instrument(s) start soon after: {', '.join(succ)}"
                    out.append(
                        Candidate(symbol, SUCCESSOR, first_ev, last, tuple(comps), why, company)
                    )
                else:
                    out.append(
                        Candidate(
                            symbol,
                            CREATE,
                            first_ev,
                            last,
                            tuple(comps),
                            f"last traded {last}; absent from the master",
                            company,
                        )
                    )
        else:
            out.append(Candidate(symbol, NEEDS_EVIDENCE, first_ev, None, tuple(comps),
                                 "no trading evidence in the bhavcopy we hold (pre-coverage, "
                                 "rename or alias gap?)"))  # fmt: skip
    return out


def create_instruments(conn: psycopg.Connection, candidates: list[Candidate]) -> dict[str, int]:
    """Insert the CREATE candidates (instrument + closed NSE alias). Returns symbol -> id."""
    ex = conn.execute("SELECT exchange_id FROM exchange WHERE mic='XNSE'").fetchone()
    if ex is None:
        raise ValueError("NSE exchange not set up")
    created: dict[str, int] = {}
    with conn.transaction():
        for c in candidates:
            if c.action != CREATE or c.last_traded is None or c.first_evidence is None:
                continue
            delisted_on = c.last_traded + timedelta(days=1)
            meta: dict[str, Any] = {
                "delisting_basis": "inferred: stopped appearing in bhavcopy, absent from master",
                "last_traded_seen": str(c.last_traded),
                "earliest_evidence": str(c.first_evidence),
                "needed_for": list(c.needed_for),
                "verified": False,
            }
            row = conn.execute(
                "INSERT INTO instrument (asset_class,exchange_id,symbol,quote_currency,"
                "delisted_on,status,meta) VALUES ('equity',%s,%s,'INR',%s,'delisted',%s)"
                " RETURNING instrument_id",
                (ex[0], c.symbol, delisted_on, Jsonb(meta)),
            ).fetchone()
            assert row is not None
            conn.execute(
                "INSERT INTO instrument_alias VALUES (%s,'nse',%s,NULL,%s,%s)",
                (row[0], c.symbol, min(c.first_evidence, c.last_traded), delisted_on),
            )
            created[c.symbol] = int(row[0])
    return created


def partitions_to_reload(conn: psycopg.Connection, symbols: set[str]) -> list[date]:
    """Loaded bhavcopy days whose audit shows any of `symbols` was dropped as unknown."""
    rows = conn.execute(
        "SELECT DISTINCT partition FROM partition_load, jsonb_array_elements_text("
        "detail->'unknown_symbols') s WHERE status='loaded' AND s = ANY(%s) ORDER BY 1",
        (sorted(symbols),),
    ).fetchall()
    return [r[0] for r in rows]


def load_symbols(
    conn: psycopg.Connection, lake: LocalLake, day: date, symbols: set[str], now: datetime
) -> int:
    """Insert the stored day's bars for `symbols` (now known) into the day's existing dataset
    version, from the stored raw file (never the network). Idempotent. Returns rows inserted."""
    last = conn.execute(
        "SELECT raw_version, dataset_version FROM partition_load WHERE source='nse'"
        " AND dataset='bhav' AND partition=%s AND status IN ('loaded','noop')"
        " ORDER BY id DESC LIMIT 1",
        (day,),
    ).fetchone()
    if last is None:
        return 0
    manifest = lake.versions("nse", "bhav", day)[last[0] - 1]
    provider = NseBhavcopy(lambda _u: b"", nse())
    spec = SPECS[provider.freq("bhav")]
    bars = provider.parse("bhav", day, lake.get(manifest))
    known: dict[str, int] = dict(
        conn.execute(
            "SELECT source_symbol, instrument_id FROM instrument_alias WHERE source='nse'"
            " AND source_symbol = ANY(%s) AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
            (sorted(symbols), day, day),
        ).fetchall()
    )
    cols = ["instrument_id", "ts", "open", "high", "low", "close", "volume", *spec.extras,
            "source", "dataset_version", "ingested_at"]  # fmt: skip
    sql = (f"INSERT INTO {spec.table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})"
           " ON CONFLICT DO NOTHING")  # fmt: skip
    inserted = 0
    for b in bars:
        if b.symbol in known:
            extras = tuple(b.extra.get(c) for c in spec.extras)
            row = (known[b.symbol], b.ts, b.open, b.high, b.low, b.close, b.volume, *extras,
                   "nse", last[1], require_utc(now))  # fmt: skip
            inserted += conn.execute(sql, row).rowcount
    return inserted

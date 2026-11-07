"""Sync NSE equities into the instrument master. Adds new listings; REPORTS (never auto-deletes or
delists) symbols that disappeared, so a partial file cannot damage history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from algo.data.providers.nse_security_master import Security
from algo.data.providers.nse_symbol_changes import SymbolChange
from algo.data.store.instruments import InstrumentRepo

DEFAULT_TICK = Decimal("0.05")
TERMS_NOTE = "assumed-default-tick"  # security master carries no tick size; verify per instrument


@dataclass
class SyncResult:
    added: list[str]
    missing: list[str]  # known to us (active nse alias) but absent from today's file


def sync_equities(
    conn: psycopg.Connection, exchange_id: int, secs: list[Security], on: date
) -> SyncResult:
    repo = InstrumentRepo(conn)
    # open-ended alias = currently mapped, even if it starts after `on` (future listing)
    known = {r[0] for r in conn.execute(
        "SELECT source_symbol FROM instrument_alias WHERE source='nse' AND valid_to IS NULL"
    )}  # fmt: skip
    added = []
    with conn.transaction():
        for s in secs:
            if s.symbol in known:
                continue
            iid = repo.add_instrument(exchange_id, s.symbol, "equity", isin=s.isin,
                                      listed_on=s.listed_on, name=s.name)  # fmt: skip
            repo.add_alias(iid, "nse", s.symbol, s.listed_on)
            repo.add_terms(iid, s.listed_on, None, s.lot_size, DEFAULT_TICK, Decimal(1),
                           margin_rule_version=TERMS_NOTE)  # fmt: skip
            added.append(s.symbol)
    return SyncResult(added, sorted(known - {s.symbol for s in secs}))


@dataclass
class SymbolChangeResult:
    applied: list[str]  # "OLD->NEW"
    unchanged: list[str]  # already applied
    not_in_universe: int  # NEW symbol is not an equity we hold (MFs, ETFs, delisted...)
    conflicts: list[str]  # old symbol already used by another instrument in that period


def apply_symbol_changes(
    conn: psycopg.Connection, changes: list[SymbolChange]
) -> SymbolChangeResult:
    """Give renamed stocks one continuous history: the new symbol's alias starts at the change date
    and an alias for the old symbol covers [original start, change date). Newest first, so chains
    (TELCO -> TATAMOTORS -> TMPV) resolve."""
    res = SymbolChangeResult([], [], 0, [])
    for ch in sorted(changes, key=lambda c: c.effective, reverse=True):
        tag = f"{ch.old}->{ch.new}"
        row = conn.execute(
            "SELECT instrument_id, valid_from FROM instrument_alias WHERE source='nse' "
            "AND source_symbol=%s AND valid_from<%s AND (valid_to IS NULL OR valid_to>%s) "
            "ORDER BY valid_from DESC LIMIT 1",
            (ch.new, ch.effective, ch.effective),
        ).fetchone()
        if row is None:
            applied = conn.execute(
                "SELECT 1 FROM instrument_alias WHERE source='nse' AND source_symbol=%s "
                "AND valid_from=%s",
                (ch.new, ch.effective),
            ).fetchone()
            if applied:
                res.unchanged.append(tag)
            else:
                res.not_in_universe += 1
            continue
        iid, start = row
        try:
            with conn.transaction():
                conn.execute(
                    "UPDATE instrument_alias SET valid_from=%s WHERE source='nse' "
                    "AND source_symbol=%s AND instrument_id=%s AND valid_from=%s",
                    (ch.effective, ch.new, iid, start),
                )
                conn.execute(
                    "INSERT INTO instrument_alias (instrument_id,source,source_symbol,valid_from,"
                    "valid_to) VALUES (%s,'nse',%s,%s,%s)",
                    (iid, ch.old, start, ch.effective),
                )
            res.applied.append(tag)
        except psycopg.errors.ExclusionViolation:
            res.conflicts.append(tag)
    return res


def load_index_snapshot(
    conn: psycopg.Connection, index_id: str, as_of: date, symbols: list[str]
) -> tuple[int, list[str]]:
    """Store constituents as a dated snapshot (history NOT known). Returns (stored, unknown)."""
    stored, unknown = 0, []
    with conn.transaction():
        for sym in symbols:
            row = conn.execute(
                "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s"
                " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
                (sym, as_of, as_of),
            ).fetchone()
            if row is None:
                unknown.append(sym)
                continue
            cur = conn.execute(
                "INSERT INTO index_snapshot VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (index_id, as_of, row[0]),
            )
            stored += cur.rowcount
    return stored, unknown

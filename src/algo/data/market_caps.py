# ruff: noqa: E501
"""AMFI market-cap lists in the database (migration 044): load one, see which are loaded, and ask which segment every stock
was in on a given day, from the list in force that day (none before the first list is relied on)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from algo.data.amfi_caps import CapList, effective_from, segment_of


@dataclass(frozen=True)
class LoadResult:
    companies: int
    matched: int


def _match(conn: psycopg.Connection, isin: str | None, nse: str | None, on: date) -> int | None:
    """Our instrument for a listed company: by ISIN, else by the NSE symbol that was valid on the list's period end."""
    if isin is not None:
        row = conn.execute("SELECT instrument_id FROM instrument WHERE isin=%s", (isin,)).fetchone()
        if row is not None:
            return int(row[0])
    if nse is not None:
        row = conn.execute(
            "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s AND valid_from <= %s"
            " AND (valid_to IS NULL OR valid_to > %s) ORDER BY valid_from DESC LIMIT 1",
            (nse, on, on),
        ).fetchone()
        if row is not None:
            return int(row[0])
    return None


def load_list(
    conn: psycopg.Connection, cap_list: CapList, url: str, sha256: str, now: datetime
) -> LoadResult:
    """Store one list, replacing any earlier load of the same period."""
    ids = [_match(conn, r.isin, r.nse_symbol, cap_list.period_end) for r in cap_list.rows]
    matched = sum(i is not None for i in ids)
    with conn.transaction():
        conn.execute("DELETE FROM market_cap_rank WHERE period_end=%s", (cap_list.period_end,))
        conn.execute("DELETE FROM market_cap_list WHERE period_end=%s", (cap_list.period_end,))
        conn.execute(
            "INSERT INTO market_cap_list (period_end, effective_from, companies, matched, source_url, raw_sha256, loaded_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                cap_list.period_end,
                effective_from(cap_list.period_end),
                len(cap_list.rows),
                matched,
                url,
                sha256,
                now,
            ),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO market_cap_rank (period_end, position, rank, isin, nse_symbol, name, avg_cap, segment, instrument_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(cap_list.period_end, pos, r.rank, r.isin, r.nse_symbol, r.name, r.avg_cap, segment_of(r.rank), iid)
                 for pos, (r, iid) in enumerate(zip(cap_list.rows, ids, strict=True), 1)],
            )  # fmt: skip
    return LoadResult(len(cap_list.rows), matched)


def list_status(conn: psycopg.Connection) -> list[dict[str, Any]]:
    keys = ["period_end", "effective_from", "companies", "matched", "source_url"]
    rows = conn.execute(
        f"SELECT {', '.join(keys)} FROM market_cap_list ORDER BY period_end"
    ).fetchall()
    return [dict(zip(keys, r, strict=True)) for r in rows]


def segments_on(conn: psycopg.Connection, day: date) -> dict[int, tuple[str, int]]:
    """instrument_id -> (segment, rank) from the list in force on `day`; empty before the first list is relied on."""
    rows = conn.execute(
        "SELECT instrument_id, segment, rank FROM market_cap_rank WHERE instrument_id IS NOT NULL AND period_end ="
        " (SELECT max(period_end) FROM market_cap_list WHERE effective_from <= %s) ORDER BY position",
        (day,),
    ).fetchall()
    out: dict[int, tuple[str, int]] = {}
    for iid, seg, rank in rows:
        out.setdefault(
            int(iid), (seg, int(rank))
        )  # a company listed twice keeps its better (first) rank
    return out

# ruff: noqa: E501
"""The screener's table: one row per listed stock with its fundamental ratios (as filed, point-in-time via algo.data.ratios) and
technical fields, built in bulk from the database and cached until the latest bar or filing changes.

Prices are unadjusted bhavcopy closes, so history is cut at the latest split/bonus: indicators needing more history than has
passed since then are None (never wrong). Cash dividends do not distort these fields."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.data import ratios as fr
from algo.data import sectors as sec
from algo.indicators.catalog import Bars
from algo.screener import smart_money
from algo.screener.engine import FIELDS
from algo.screener.technical import technicals

WINDOW_DAYS, STALE_DAYS, FILING_YEARS = 420, 10, 3


def _bars(conn: psycopg.Connection, latest: date) -> dict[int, list[tuple[Any, ...]]]:
    out: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for iid, day, o, h, lo, c, v in conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open, high, low, close, volume"
        " FROM bar_1d WHERE source='nse' AND ts >= %s::date - %s ORDER BY instrument_id, ts, dataset_version DESC",
        (latest, WINDOW_DAYS),
    ):
        out[iid].append((day, o, h, lo, c, v))
    return out


def quarters_since(
    conn: psycopg.Connection, since: date, ids: Sequence[int] | None = None
) -> dict[tuple[int, str], list[fr.Quarter]]:
    """Every filing with a period end on or after `since`, by (instrument, basis); only these instruments if `ids` is given."""
    only, args = (
        ("", (since,)) if ids is None else (" AND f.instrument_id = ANY(%s)", (since, list(ids)))
    )
    facts: dict[int, dict[str, dict[str, Decimal]]] = {}
    for fid, scope, metric, value in conn.execute(
        "SELECT x.filing_id, x.scope, x.metric, x.value FROM fundamental_fact x JOIN fundamental_filing f USING (filing_id)"
        " WHERE f.instrument_id IS NOT NULL AND f.period_end >= %s AND x.metric ~ '^[A-Z]'" + only,
        args,
    ):
        facts.setdefault(fid, {"QUARTER": {}, "YTD": {}, "INSTANT": {}})[scope][metric] = value
    out: dict[tuple[int, str], list[fr.Quarter]] = defaultdict(list)
    for fid, iid, basis, end, filed, bank in conn.execute(
        "SELECT filing_id, instrument_id, basis, period_end, filed_at, bank FROM fundamental_filing"
        " WHERE instrument_id IS NOT NULL AND period_end >= %s" + only.replace("f.", ""),
        args,
    ):
        f = facts.get(fid, {})
        out[(iid, basis)].append(
            fr.Quarter(
                end, filed, bank, f.get("QUARTER", {}), f.get("YTD", {}), f.get("INSTANT", {})
            )
        )
    return out


def compute(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Calculate the table from bars and filings (slow: 30-50 s). Runs in the refresh job, not on a request."""
    latest = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
    ).fetchone()
    if latest is None or latest[0] is None:
        return []
    day = latest[0]
    names = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT instrument_id, symbol, name FROM instrument WHERE asset_class='equity' AND delisted_on IS NULL"
        )
    }
    last_split: dict[int, date] = dict(
        conn.execute(
            "SELECT instrument_id, max(ex_date) FROM corporate_action WHERE kind IN ('split','bonus') AND status='ok' AND ex_date <= %s GROUP BY 1",
            (day,),
        ).fetchall()
    )
    dividends: dict[int, Decimal] = dict(
        conn.execute(
            "SELECT instrument_id, sum(amount) FROM corporate_action WHERE kind='dividend' AND status='ok' AND amount IS NOT NULL"
            " AND ex_date > %s::date - 365 AND ex_date <= %s GROUP BY 1",
            (day, day),
        ).fetchall()
    )
    segment: dict[int, str] = dict(
        conn.execute(
            "SELECT instrument_id, segment FROM market_cap_rank WHERE instrument_id IS NOT NULL AND period_end ="
            " (SELECT max(period_end) FROM market_cap_list WHERE effective_from <= %s)",
            (day,),
        ).fetchall()
    )
    quarters = quarters_since(conn, day - timedelta(days=365 * FILING_YEARS))
    smart = smart_money.compute(conn, day, {sym: iid for iid, (sym, _) in names.items()})
    rows: list[dict[str, Any]] = []
    for iid, bars in _bars(conn, day).items():
        if iid not in names or bars[-1][0] < day - timedelta(days=STALE_DAYS):
            continue
        cut = last_split.get(iid)
        kept = [b for b in bars if cut is None or b[0] >= cut][-300:]
        symbol, name = names[iid]
        row: dict[str, Any] = {
            "instrument_id": iid,
            "symbol": symbol,
            "name": name,
            "as_of": bars[-1][0].isoformat(),
        }
        row.update(technicals(Bars(*([b[i] for b in kept] for i in range(1, 6)))))
        row["segment"] = segment.get(iid)
        row.update(smart.get(iid, {}))
        basis = "CONSOLIDATED" if (iid, "CONSOLIDATED") in quarters else "STANDALONE"
        known = fr.known_quarters(quarters.get((iid, basis), []))
        if known:
            split_after = cut is not None and cut > known[0].filed_at.date()
            market = fr.Market(bars[-1][4], bars[-1][0], dividends.get(iid), split_after)
            row.update({k: v.value for k, v in fr.compute(known, market).items()})
            row["latest_period"] = known[0].period_end.isoformat()
        rows.append(row)
    return add_sector_view(rows, sec.sectors_on(conn, day))


def add_sector_view(rows: list[dict[str, Any]], sector_of: dict[int, str]) -> list[dict[str, Any]]:
    """Each stock's sector, the median P/E of its OTHER sector peers (three at least) and its own P/E relative to that median."""
    pe = {r["instrument_id"]: r.get("pe") for r in rows}
    for r in rows:
        peer = sec.peer_median(pe, sector_of, r["instrument_id"], min_peers=3)
        r["sector"] = peer.sector
        r["pe_sector_median"] = peer.median
        r["pe_vs_sector"] = sec.relative(r.get("pe"), peer)
    return rows


def refresh(conn: psycopg.Connection) -> int:
    """Rebuild the stored table in one transaction (readers see the old rows until it commits). Returns the row count."""
    rows = compute(conn)
    with conn.transaction():
        conn.execute("DELETE FROM screener_snapshot")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO screener_snapshot (instrument_id, as_of, row, built_at) VALUES (%s,%s,%s,now())",
                [
                    (
                        r["instrument_id"],
                        r["as_of"],
                        Jsonb({k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()}),
                    )
                    for r in rows
                ],
            )
    return len(rows)


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: Decimal(v) if isinstance(v, str) and k in FIELDS and FIELDS[k].unit != "text" else v
        for k, v in row.items()
    }


def build(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """The stored table. Built once here if the refresh job has never run."""
    stored = conn.execute("SELECT row FROM screener_snapshot").fetchall()
    if not stored:
        refresh(conn)
        stored = conn.execute("SELECT row FROM screener_snapshot").fetchall()
    return [_decode(r[0]) for r in stored]

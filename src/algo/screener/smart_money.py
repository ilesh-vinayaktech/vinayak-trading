# ruff: noqa: E501
"""The screener's "smart money" fields per stock, from the NSE tables (algo.data.nse_intel): delivery %, who holds the company
(promoter, FII, DII, mutual funds, retail) and how that changed since the previous quarter, insider buying and bulk/block
deals. A figure with no data behind it is simply absent (never zero), so a screen never matches on "unknown".

These come from the latest filings as published, not as known on an earlier date: screens on them are for looking at today,
not for backtests (the frontend therefore does not let a screen using them be saved as a strategy)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

CRORE = Decimal(10**7)
DELIVERY_DAYS, INSIDER_DAYS, DEAL_DAYS = 20, 90, 30


def _delivery(conn: psycopg.Connection, day: date) -> dict[int, dict[str, Decimal]]:
    series: dict[int, list[Decimal]] = defaultdict(list)
    for iid, volume, deliv in conn.execute(
        "SELECT instrument_id, volume, delivery_qty FROM ("
        " SELECT DISTINCT ON (instrument_id, ts) instrument_id, ts, volume, delivery_qty FROM bar_1d"
        " WHERE source='nse' AND series='EQ' AND ts >= %s::date - 40 AND ts < %s::date + 1"
        " ORDER BY instrument_id, ts, dataset_version DESC) x ORDER BY instrument_id, ts",
        (day, day),
    ):
        if deliv is not None and volume > 0:
            series[iid].append(100 * deliv / volume)
    out: dict[int, dict[str, Decimal]] = {}
    for iid, pcts in series.items():
        recent = pcts[-DELIVERY_DAYS:]
        avg = sum(recent, Decimal(0)) / len(recent)
        out[iid] = {"delivery_pct": pcts[-1], "delivery_pct_20d": avg}
        if avg > 0:
            out[iid]["delivery_vs_avg"] = pcts[-1] / avg
    return out


def _holdings(
    conn: psycopg.Connection, symbols: Mapping[str, int]
) -> dict[int, dict[str, Decimal]]:
    """Latest filing per stock, and change against the filing for the previous period (only where both report the figure)."""
    by_symbol: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT DISTINCT ON (symbol, period_end) symbol, period_end, promoter_pct, fii_pct, dii_pct, mf_pct, retail_pct"
        " FROM nse_shareholding ORDER BY symbol, period_end, broadcast_at DESC NULLS LAST"
    ):
        by_symbol[r[0]].append(r)
    cols = ("promoter_pct", "fii_pct", "dii_pct", "mf_pct", "retail_pct")
    out: dict[int, dict[str, Decimal]] = {}
    for sym, filings in by_symbol.items():
        iid = symbols.get(sym)
        if iid is None:
            continue
        # the newest filing that has the split also supplies FII / DII; the headline promoter % alone is older-compatible
        last, prev = filings[-1], filings[-2] if len(filings) > 1 else None
        row = {c: Decimal(last[2 + i]) for i, c in enumerate(cols) if last[2 + i] is not None}
        if prev is not None:
            for i, c in enumerate(cols[:4]):
                if last[2 + i] is not None and prev[2 + i] is not None:
                    row[c.replace("_pct", "_change")] = Decimal(last[2 + i]) - Decimal(prev[2 + i])
        out[iid] = row
    return out


def _insider(
    conn: psycopg.Connection, day: date, symbols: Mapping[str, int]
) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    for sym, net, buys in conn.execute(
        "SELECT symbol, sum(CASE lower(transaction_type) WHEN 'buy' THEN value WHEN 'sell' THEN -value ELSE 0 END), count(*) FILTER (WHERE lower(transaction_type) = 'buy')"
        " FROM nse_insider_trade WHERE broadcast_at >= %s::date - %s AND broadcast_at < %s::date + 1 AND value IS NOT NULL GROUP BY symbol",
        (day, INSIDER_DAYS, day),
    ):
        if sym in symbols:
            out[symbols[sym]] = {"insider_net_90d": net / CRORE, "insider_buys_90d": Decimal(buys)}
    return out


def _deals(
    conn: psycopg.Connection, day: date, symbols: Mapping[str, int]
) -> dict[int, dict[str, Decimal]]:
    out: dict[int, dict[str, Decimal]] = {}
    for sym, net in conn.execute(
        "SELECT symbol, sum(CASE side WHEN 'BUY' THEN quantity * price ELSE -quantity * price END) FROM nse_bulk_block_deal"
        " WHERE trade_date > %s::date - %s AND trade_date <= %s GROUP BY symbol",
        (day, DEAL_DAYS, day),
    ):
        if sym in symbols:
            out[symbols[sym]] = {"deal_net_30d": net / CRORE}
    return out


def compute(
    conn: psycopg.Connection, day: date, symbols: Mapping[str, int]
) -> dict[int, dict[str, Decimal]]:
    """instrument_id -> {field: value}; `symbols` maps NSE symbol -> instrument_id for the listed stocks."""
    merged: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for part in (
        _delivery(conn, day),
        _holdings(conn, symbols),
        _insider(conn, day, symbols),
        _deals(conn, day, symbols),
    ):
        for iid, vals in part.items():
            merged[iid].update(vals)
    return dict(merged)

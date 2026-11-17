# ruff: noqa: E501
"""NSE smart-money data, read-only: FII/DII flows, most active, delivery %, bulk/block deals, insider trades, and everything
for one stock (`/instrument/{id}`: delivery history, who holds it, insider trades, deals). Every number comes from rows
`scripts/ingest_nse_intel.py` and the bhavcopy load wrote. Default permission for GET (research:read).

Callers: frontend/app/market/intel/page.tsx, frontend/components/charts/SmartMoneyPanel.tsx, tests/integration/test_nse_routes.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from algo.api.security import WConn
from algo.data import nse_intel

router = APIRouter(prefix="/api/nse", tags=["nse"])


def _f(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _rows(rows: list[tuple[Any, ...]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{k: _iso(_f(v)) for k, v in zip(keys, r, strict=True)} for r in rows]


def _with_ids(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `id` (the instrument's id, for linking to its page) to rows that carry a NSE `symbol`; None when the symbol is not a listed stock here."""
    ids = dict(
        conn.execute(
            "SELECT symbol, max(instrument_id) FROM instrument WHERE asset_class='equity' AND delisted_on IS NULL AND symbol = ANY(%s) GROUP BY symbol",
            (sorted({r["symbol"] for r in rows}),),
        ).fetchall()
    )
    return [{**r, "id": ids.get(r["symbol"])} for r in rows]


def _day(conn: Any, day: date | None) -> date | None:
    if day is not None:
        return day
    r = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source='nse'"
    ).fetchone()
    return r[0] if r else None


@router.get("/flows")
def flows(conn: WConn, days: int = Query(60, ge=1, le=1000)) -> dict[str, Any]:
    """FII and DII cash-market buy / sell / net per session (Rs crore), newest first. History starts when the daily job first ran."""
    rows = conn.execute(
        "SELECT trade_date, max(buy_value) FILTER (WHERE category='FII'), max(sell_value) FILTER (WHERE category='FII'), max(net_value) FILTER (WHERE category='FII'),"
        " max(buy_value) FILTER (WHERE category='DII'), max(sell_value) FILTER (WHERE category='DII'), max(net_value) FILTER (WHERE category='DII')"
        " FROM nse_fii_dii GROUP BY trade_date ORDER BY trade_date DESC LIMIT %s",
        (days,),
    ).fetchall()
    return {
        "rows": _rows(
            rows, ("date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net")
        )
    }


@router.get("/most-active")
def most_active(
    conn: WConn,
    by: str = Query("value", pattern="^(value|volume)$"),
    day: date | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    d = _day(conn, day)
    rows = [] if d is None else nse_intel.most_active(conn, d, by=by, limit=limit)
    return {
        "day": _iso(d),
        "rows": _with_ids(conn, _rows(rows, ("symbol", "close", "volume", "traded_value"))),
    }


@router.get("/delivery")
def delivery(
    conn: WConn,
    day: date | None = None,
    min_volume: int = Query(100000, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    d = _day(conn, day)
    rows = [] if d is None else nse_intel.delivery_pct(conn, d, min_volume=min_volume, limit=limit)
    return {
        "day": _iso(d),
        "rows": _with_ids(
            conn, _rows(rows, ("symbol", "close", "volume", "delivery_qty", "delivery_pct"))
        ),
    }


@router.get("/deals")
def deals(
    conn: WConn, days: int = Query(7, ge=1, le=365), limit: int = Query(200, ge=1, le=1000)
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT trade_date, kind, symbol, client, side, quantity, price, quantity * price / 10000000, remarks FROM nse_bulk_block_deal"
        " WHERE trade_date > (SELECT coalesce(max(trade_date), current_date) FROM nse_bulk_block_deal) - %s ORDER BY trade_date DESC, quantity * price DESC LIMIT %s",
        (days, limit),
    ).fetchall()
    keys = ("date", "kind", "symbol", "client", "side", "quantity", "price", "value_cr", "remarks")
    return {"rows": _with_ids(conn, _rows(rows, keys))}


_INSIDER = (
    "did",
    "symbol",
    "person",
    "category",
    "type",
    "mode",
    "quantity",
    "value",
    "pct_after",
    "from_date",
    "intimation_date",
    "broadcast_at",
)
_INSIDER_SQL = "SELECT did, symbol, person, person_category, transaction_type, acquisition_mode, quantity, value, pct_after, from_date, intimation_date, broadcast_at FROM nse_insider_trade"


@router.get("/insider")
def insider(
    conn: WConn, days: int = Query(30, ge=1, le=730), limit: int = Query(200, ge=1, le=1000)
) -> dict[str, Any]:
    rows = conn.execute(
        f"{_INSIDER_SQL} WHERE broadcast_at > (SELECT coalesce(max(broadcast_at), now()) FROM nse_insider_trade) - make_interval(days => %s) ORDER BY broadcast_at DESC LIMIT %s",  # noqa: S608
        (days, limit),
    ).fetchall()
    return {"rows": _with_ids(conn, _rows(rows, _INSIDER))}


@router.get("/instrument/{instrument_id}")
def instrument(instrument_id: int, conn: WConn) -> dict[str, Any]:
    """Everything the NSE tables hold for one stock (matched on its NSE symbol)."""
    r = conn.execute(
        "SELECT symbol FROM instrument WHERE instrument_id = %s", (instrument_id,)
    ).fetchone()
    if r is None:
        raise HTTPException(404, "no such instrument")
    sym = r[0]
    delivery_rows = conn.execute(
        "SELECT d, close, volume, delivery_qty, CASE WHEN volume > 0 THEN round(100 * delivery_qty / volume, 2) END FROM ("
        " SELECT DISTINCT ON (ts) (ts AT TIME ZONE 'Asia/Kolkata')::date d, close, volume, delivery_qty FROM bar_1d"
        " WHERE instrument_id = %s AND source='nse' AND series='EQ' AND delivery_qty IS NOT NULL ORDER BY ts DESC, dataset_version DESC LIMIT 60) x ORDER BY d DESC",
        (instrument_id,),
    ).fetchall()
    holdings = conn.execute(
        "SELECT * FROM (SELECT DISTINCT ON (period_end) period_end, promoter_pct, fii_pct, dii_pct, mf_pct, insurance_pct, retail_pct, public_pct, broadcast_at, revised"
        " FROM nse_shareholding WHERE symbol = %s ORDER BY period_end DESC, broadcast_at DESC NULLS LAST) x ORDER BY period_end DESC LIMIT 12",
        (sym,),
    ).fetchall()
    ins = conn.execute(
        f"{_INSIDER_SQL} WHERE symbol = %s ORDER BY broadcast_at DESC LIMIT 50", (sym,)
    ).fetchall()  # noqa: S608
    dl = conn.execute(
        "SELECT trade_date, kind, client, side, quantity, price, quantity * price / 10000000, remarks FROM nse_bulk_block_deal WHERE symbol = %s ORDER BY trade_date DESC LIMIT 50",
        (sym,),
    ).fetchall()
    return {
        "symbol": sym,
        "delivery": _rows(
            delivery_rows, ("date", "close", "volume", "delivery_qty", "delivery_pct")
        ),
        "holdings": _rows(
            holdings,
            (
                "period_end",
                "promoter",
                "fii",
                "dii",
                "mf",
                "insurance",
                "retail",
                "public",
                "filed_at",
                "revised",
            ),
        ),
        "insider": _rows(ins, _INSIDER),
        "deals": _rows(
            dl, ("date", "kind", "client", "side", "quantity", "price", "value_cr", "remarks")
        ),
    }

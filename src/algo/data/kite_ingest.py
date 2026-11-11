# ruff: noqa: E501  (SQL statements and docstrings are kept readable)
"""Load 1-minute Kite candles into bar_1m, window by window, resumable and honest about what it holds.

Kite adjusts prices and volumes for splits and bonuses as of the fetch date, so each row records `adjusted_through`.
A window already loaded (or empty) is never asked twice, except the window that touches today (still filling). A window
whose prices are inconsistent is refused whole and recorded as failed. An expired session raises KiteTokenExpired; what
was already stored stays, and the next run resumes at the window it was in. The caller injects the client."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg

from algo.data.bars import Bar
from algo.data.providers.kite import Candle, KiteInstrument, windows
from algo.data.quality.checks import validity

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "kite"


class MinuteClient(Protocol):
    def historical(
        self, instrument_token: int, interval: str, start: datetime, end: datetime
    ) -> list[Candle]: ...


@dataclass
class MinuteLoad:
    loaded: int = 0
    empty: int = 0
    skipped: int = 0
    failed: int = 0
    rows: int = 0


@dataclass(frozen=True)
class MapResult:
    mapped: list[tuple[KiteInstrument, int]] = field(default_factory=list)
    unmatched: list[tuple[str, str]] = field(default_factory=list)


def map_universe(
    conn: psycopg.Connection,
    kite: Sequence[KiteInstrument],
    universe: Sequence[tuple[str, str, str]],
) -> MapResult:
    """universe = (NSE symbol, ISIN, series). Kite names RR/BE series with a suffix (EMBASSY-RR, HFCL-BE). A match needs
    the Kite instrument AND our security (by ISIN, else by the current NSE alias); anything else is reported."""
    by_symbol = {k.tradingsymbol: k for k in kite}
    out = MapResult()
    for symbol, isin, series in universe:
        if symbol.startswith("DUMMY"):
            out.unmatched.append((symbol, "placeholder, not a real security"))
            continue
        k = next((by_symbol[c] for c in (symbol, f"{symbol}-{series}") if c in by_symbol), None)
        if k is None:
            out.unmatched.append((symbol, "no Kite instrument"))
            continue
        row = conn.execute("SELECT instrument_id FROM instrument WHERE isin=%s", (isin,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s AND valid_to IS NULL",
                (symbol,),
            ).fetchone()
        if row is None:
            out.unmatched.append((symbol, "not in our instrument master"))
            continue
        out.mapped.append((k, int(row[0])))
    return out


def upsert_kite_instruments(
    conn: psycopg.Connection, mapped: Sequence[tuple[KiteInstrument, int]], now: datetime
) -> int:
    for k, iid in mapped:
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id, refreshed_at)"
            " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (instrument_token) DO UPDATE SET exchange_token=EXCLUDED.exchange_token,"
            " tradingsymbol=EXCLUDED.tradingsymbol, name=EXCLUDED.name, instrument_id=EXCLUDED.instrument_id,"
            " refreshed_at=EXCLUDED.refreshed_at",
            (k.instrument_token, k.exchange_token, k.tradingsymbol, k.name, iid, now),
        )
    return len(mapped)


def _digest(candles: Sequence[Candle]) -> str:
    h = hashlib.sha256()
    for c in candles:
        h.update(f"{c.ts.isoformat()}|{c.open}|{c.high}|{c.low}|{c.close}|{c.volume}\n".encode())
    return h.hexdigest()


def _ledger(
    conn: psycopg.Connection,
    iid: int,
    ws: date,
    we: date,
    status: str,
    n: int,
    sha: str | None,
    adj: date,
    detail: str,
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO kite_fetch (instrument_id, window_start, window_end, status, candles, content_sha256, adjusted_through,"
        " detail, fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (instrument_id, window_start, window_end)"
        " DO UPDATE SET status=EXCLUDED.status, candles=EXCLUDED.candles, content_sha256=EXCLUDED.content_sha256,"
        " adjusted_through=EXCLUDED.adjusted_through, detail=EXCLUDED.detail, fetched_at=EXCLUDED.fetched_at",
        (iid, ws, we, status, n, sha, adj, detail, now),
    )


def _insert(
    conn: psycopg.Connection,
    instrument_id: int,
    candles: Sequence[Candle],
    adjusted_through: date,
    now: datetime,
) -> int:
    """Bulk insert through a staging table: one COPY and one INSERT, about 15x faster than row by row."""
    if not candles:
        return 0
    conn.execute(
        "CREATE TEMP TABLE kite_stage (ts timestamptz, open numeric, high numeric, low numeric, close numeric, volume numeric, oi numeric) ON COMMIT DROP"
    )
    with conn.cursor().copy("COPY kite_stage FROM STDIN") as cp:
        for c in candles:
            cp.write_row((c.ts, c.open, c.high, c.low, c.close, c.volume, c.oi))
    return conn.execute(
        "INSERT INTO bar_1m (instrument_id, ts, open, high, low, close, volume, oi, source, adjusted_through, dataset_version, ingested_at)"
        " SELECT %s, ts, open, high, low, close, volume, oi, %s, %s, 1, %s FROM kite_stage ON CONFLICT DO NOTHING",
        (instrument_id, SOURCE, adjusted_through, now.astimezone(UTC)),
    ).rowcount


def load_minutes(
    conn: psycopg.Connection,
    client: MinuteClient,
    token: int,
    instrument_id: int,
    start: date,
    end: date,
    now: datetime,
    *,
    window_days: int = 60,
) -> MinuteLoad:
    res = MinuteLoad()
    today = now.astimezone(IST).date()
    for ws, we in windows(start, end, window_days):
        done = conn.execute(
            "SELECT 1 FROM kite_fetch WHERE instrument_id=%s AND window_start=%s AND window_end=%s AND status IN ('loaded','empty')",
            (instrument_id, ws, we),
        ).fetchone()
        if done and we < today:
            res.skipped += 1
            continue
        candles = sorted(
            client.historical(
                token,
                "minute",
                datetime.combine(ws, time(0, 0), IST),
                datetime.combine(we, time(23, 59, 59), IST),
            ),
            key=lambda c: c.ts,
        )
        issues = validity(
            [
                Bar(str(instrument_id), c.ts, c.open, c.high, c.low, c.close, c.volume)
                for c in candles
            ]
        )
        with conn.transaction():
            if issues:
                _ledger(
                    conn,
                    instrument_id,
                    ws,
                    we,
                    "failed",
                    len(candles),
                    None,
                    today,
                    "; ".join(issues[:3]),
                    now,
                )
                res.failed += 1
                continue
            n = _insert(conn, instrument_id, candles, today, now)
            _ledger(
                conn,
                instrument_id,
                ws,
                we,
                "loaded" if candles else "empty",
                len(candles),
                _digest(candles) if candles else None,
                today,
                "",
                now,
            )
        res.rows += n
        if candles:
            res.loaded += 1
        else:
            res.empty += 1
    return res

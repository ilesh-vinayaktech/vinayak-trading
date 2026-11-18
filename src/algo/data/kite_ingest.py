# ruff: noqa: E501  (SQL statements and docstrings are kept readable)
"""Load 1-minute Kite candles into bar_1m, window by window, resumable and honest about what it holds.

Kite adjusts prices and volumes for splits and bonuses as of the fetch date, so each row records `adjusted_through`.
A window already loaded (or empty) is never asked twice, except the window that touches today (still filling). A window
whose prices are inconsistent is refused whole and recorded as failed. An expired session raises KiteTokenExpired; what
was already stored stays, and the next run resumes at the window it was in. The caller injects the client."""

from __future__ import annotations

import gzip
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

import psycopg

from algo.data.bars import Bar
from algo.data.lake import LocalLake
from algo.data.providers.kite import Candle, KiteInstrument, windows
from algo.data.quality.checks import validity

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "kite"


class MinuteClient(Protocol):
    def historical(
        self,
        instrument_token: int,
        interval: str,
        start: datetime,
        end: datetime,
        *,
        raw_sink: Callable[[bytes], None] | None = None,
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
        # the series in the list first; then BE (trade-for-trade), which Kite names with a suffix even when we do not know it
        k = next(
            (
                by_symbol[c]
                for c in (symbol, f"{symbol}-{series}", f"{symbol}-BE")
                if c in by_symbol
            ),
            None,
        )
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


def day_work(conn: psycopg.Connection) -> list[tuple[int, str, int]]:
    """(token, symbol, instrument_id) to ask Kite for, by symbol. A token that is inactive AND whose instrument has
    another active token is superseded (the stock moved series, e.g. to -BE): Kite no longer serves it ("invalid
    token") and the history comes with the new one. A history-only stock (inactive, nothing else) is still asked for."""
    return [
        (int(r[0]), str(r[1]), int(r[2]))
        for r in conn.execute(
            "SELECT k.instrument_token, k.tradingsymbol, k.instrument_id FROM kite_instrument k"
            " WHERE k.instrument_id IS NOT NULL AND NOT (NOT k.active AND EXISTS"
            "  (SELECT 1 FROM kite_instrument o WHERE o.instrument_id = k.instrument_id AND o.active))"
            " AND k.refreshed_at::date >= (SELECT max(refreshed_at)::date FROM kite_instrument)"
            " AND k.tradingsymbol NOT LIKE '%-BE' ORDER BY k.tradingsymbol"
        )
    ]


def upsert_kite_instruments(
    conn: psycopg.Connection,
    mapped: Sequence[tuple[KiteInstrument, int]],
    now: datetime,
    *,
    active: bool = True,
) -> int:
    """Store the token mapping. `active` applies to NEW rows only (the live feed follows active ones); a stock already
    stored keeps its flag, so adding history-only stocks never switches anything on or off for the feed."""
    for k, iid in mapped:
        conn.execute(
            "INSERT INTO kite_instrument (instrument_token, exchange_token, tradingsymbol, name, instrument_id, refreshed_at, active, tick_size)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (instrument_token) DO UPDATE SET exchange_token=EXCLUDED.exchange_token,"
            " tradingsymbol=EXCLUDED.tradingsymbol, name=EXCLUDED.name, instrument_id=EXCLUDED.instrument_id,"
            " refreshed_at=EXCLUDED.refreshed_at, tick_size=COALESCE(EXCLUDED.tick_size, kite_instrument.tick_size)",
            (
                k.instrument_token,
                k.exchange_token,
                k.tradingsymbol,
                k.name,
                iid,
                now,
                active,
                k.tick_size,
            ),
        )
    return len(mapped)


def master_universe(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """Every active equity in our own instrument master as (symbol, ISIN, series): the stocks worth downloading from Kite.
    ISINs starting INE are company shares; INF are funds and ETFs, which are left out. Delisted stocks have no Kite
    instrument anyway. Series is EQ; map_universe also tries the -BE name Kite uses for trade-for-trade stocks."""
    rows = conn.execute(
        "SELECT symbol, isin FROM instrument WHERE status='active' AND isin LIKE 'INE%' ORDER BY symbol"
    ).fetchall()
    return [(symbol, isin, "EQ") for symbol, isin in rows]


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
    raw_sha256: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO kite_fetch (instrument_id, window_start, window_end, status, candles, content_sha256, adjusted_through,"
        " detail, fetched_at, raw_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (instrument_id, window_start, window_end)"
        " DO UPDATE SET status=EXCLUDED.status, candles=EXCLUDED.candles, content_sha256=EXCLUDED.content_sha256,"
        " adjusted_through=EXCLUDED.adjusted_through, detail=EXCLUDED.detail, fetched_at=EXCLUDED.fetched_at,"
        " raw_sha256=EXCLUDED.raw_sha256",
        (iid, ws, we, status, n, sha, adj, detail, now, raw_sha256),
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
    lake: LocalLake | None = None,
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
        raw: list[bytes] = []
        candles = sorted(
            client.historical(
                token,
                "minute",
                datetime.combine(ws, time(0, 0), IST),
                datetime.combine(we, time(23, 59, 59), IST),
                raw_sink=raw.append,
            ),
            key=lambda c: c.ts,
        )
        raw_sha = None
        if (
            lake is not None and raw
        ):  # the bytes Kite sent, kept even if the window is refused below
            url = f"historical/{token}/minute?from={ws}&to={we}"
            raw_sha = lake.put(
                "kite",
                f"minute_{token}",
                ws,
                gzip.compress(raw[0], mtime=0),
                url=url,
                fetched_at=now,
            ).checksum
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
                    raw_sha,
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
                raw_sha,
            )
        res.rows += n
        if candles:
            res.loaded += 1
        else:
            res.empty += 1
    return res


def _day_ledger(
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
    raw_sha256: str | None,
) -> None:
    conn.execute(
        "INSERT INTO kite_day_fetch (instrument_id, window_start, window_end, status, candles, content_sha256,"
        " adjusted_through, detail, fetched_at, raw_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (instrument_id, window_start, window_end) DO UPDATE SET status=EXCLUDED.status,"
        " candles=EXCLUDED.candles, content_sha256=EXCLUDED.content_sha256, adjusted_through=EXCLUDED.adjusted_through,"
        " detail=EXCLUDED.detail, fetched_at=EXCLUDED.fetched_at, raw_sha256=EXCLUDED.raw_sha256",
        (iid, ws, we, status, n, sha, adj, detail, now, raw_sha256),
    )


def load_days(
    conn: psycopg.Connection,
    client: MinuteClient,
    token: int,
    instrument_id: int,
    start: date,
    end: date,
    now: datetime,
    *,
    window_days: int = 2000,
    lake: LocalLake | None = None,
    revise: bool = False,
) -> MinuteLoad:
    """Kite DAILY candles into bar_1d (source 'kite', ts = 09:15 IST of the day like the bhavcopy rows). Same rules as
    load_minutes: finished windows are skipped except the one touching today, an inconsistent window is refused whole,
    an expired session raises, the raw response is archived. The day candle carries the full day's volume.
    `revise`: a candle whose values differ from the latest stored one is stored as the NEXT dataset_version (the reader
    takes the highest), so the provisional candle of the evening is replaced by the final one the next morning, with
    the history kept; identical candles add nothing, and frozen days are still never touched."""
    res = MinuteLoad()
    today = now.astimezone(IST).date()
    frozen_row = conn.execute(
        "SELECT max(f.through_date) FROM data_freeze f JOIN data_freeze_item i USING (freeze_id)"
        " WHERE f.source=%s AND f.dataset='bar_1d' AND i.instrument_id=%s",
        (SOURCE, instrument_id),
    ).fetchone()
    frozen_through = None if frozen_row is None else frozen_row[0]
    for ws, we in windows(start, end, window_days):
        done = conn.execute(
            "SELECT 1 FROM kite_day_fetch WHERE instrument_id=%s AND window_start=%s AND window_end=%s AND status IN ('loaded','empty')",
            (instrument_id, ws, we),
        ).fetchone()
        if done and we < today:
            res.skipped += 1
            continue
        raw: list[bytes] = []
        candles = sorted(
            client.historical(
                token,
                "day",
                datetime.combine(ws, time(0, 0), IST),
                datetime.combine(we, time(23, 59, 59), IST),
                raw_sink=raw.append,
            ),
            key=lambda c: c.ts,
        )
        raw_sha = None
        if lake is not None and raw:
            url = f"historical/{token}/day?from={ws}&to={we}"
            raw_sha = lake.put(
                "kite", f"day_{token}", ws, gzip.compress(raw[0], mtime=0), url=url, fetched_at=now
            ).checksum
        # Kite pads the time before a listing with candles that have no price at all (some even carry a volume): there is
        # nothing usable in them, so they are left out and counted in the ledger rather than failing the whole window
        real = [c for c in candles if any((c.open, c.high, c.low, c.close))]
        note = (
            f"{len(candles) - len(real)} candle(s) without any price dropped"
            if len(real) != len(candles)
            else ""
        )
        candles = real
        issues = validity(
            [
                Bar(str(instrument_id), c.ts, c.open, c.high, c.low, c.close, c.volume)
                for c in candles
            ]
        )
        with conn.transaction():
            if issues:
                _day_ledger(
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
                    raw_sha,
                )
                res.failed += 1
                continue
            n = 0
            for c in candles:
                if frozen_through is not None and c.ts.astimezone(IST).date() <= frozen_through:
                    continue  # frozen history is never written by a routine load (the database refuses it)
                opened = datetime.combine(c.ts.astimezone(IST).date(), time(9, 15), IST)
                version = 1
                if revise:
                    last = conn.execute(
                        "SELECT open, high, low, close, volume, dataset_version FROM bar_1d WHERE instrument_id=%s"
                        " AND ts=%s AND source=%s ORDER BY dataset_version DESC LIMIT 1",
                        (instrument_id, opened, SOURCE),
                    ).fetchone()
                    if last is not None:
                        if tuple(last[:5]) == (c.open, c.high, c.low, c.close, c.volume):
                            continue  # nothing changed
                        version = int(last[5]) + 1
                n += conn.execute(
                    "INSERT INTO bar_1d (instrument_id, ts, open, high, low, close, volume, source, dataset_version, ingested_at,"
                    " adjusted_through) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        instrument_id,
                        opened,
                        c.open,
                        c.high,
                        c.low,
                        c.close,
                        c.volume,
                        SOURCE,
                        version,
                        now.astimezone(UTC),
                        today,
                    ),
                ).rowcount
            _day_ledger(
                conn,
                instrument_id,
                ws,
                we,
                "loaded" if candles else "empty",
                len(candles),
                _digest(candles) if candles else None,
                today,
                note,
                now,
                raw_sha,
            )
        res.rows += n
        if candles:
            res.loaded += 1
        else:
            res.empty += 1
    return res

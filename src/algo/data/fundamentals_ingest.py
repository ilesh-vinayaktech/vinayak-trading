# ruff: noqa: E501  (docstrings and one-line SQL are kept readable)
"""Load one company's quarterly results: listing -> raw XBRL files into the lake (kept untouched, sha256) -> parsed facts.

Resumable and polite: a filing already stored is never re-downloaded; every filing that cannot be loaded is recorded with a
reason (a gap is explicit, never silent); and a 401/403 from the exchange stops the whole run (`Blocked`) instead of retrying.
The caller injects `get(url) -> bytes` (the throttled NseClient in production)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime

import psycopg

from algo.data.fundamentals import FilingMismatch, note_unloaded, store_extra, store_filing
from algo.data.lake import LocalLake
from algo.data.providers.nse_client import NseHttpError
from algo.data.providers.nse_results import (
    Filing,
    XbrlError,
    parse_integrated_listing,
    parse_listing,
    parse_xbrl,
)

LISTING_URL = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={symbol}&period=Quarterly"

INTEGRATED_URL = "https://www.nseindia.com/api/integrated-filing-results?index=equities&type=Integrated%20Filing-%20Financials&symbol={symbol}"


class Blocked(Exception):
    """The exchange refused us (401/403): stop, do not retry."""


@dataclass
class IngestResult:
    symbol: str
    listed: int = 0
    stored: int = 0
    already: int = 0
    noted: dict[str, int] = field(default_factory=dict)

    def note(self, reason: str) -> None:
        self.noted[reason] = self.noted.get(reason, 0) + 1


def _fetch(get: Callable[[str], bytes], url: str) -> bytes:
    try:
        return get(url)
    except NseHttpError as e:
        if e.status in (401, 403):
            raise Blocked(f"NSE refused ({e.status}) {url}") from e
        raise


def ingest_symbol(
    conn: psycopg.Connection,
    lake: LocalLake,
    get: Callable[[str], bytes],
    symbol: str,
    now: datetime,
    *,
    since: date = date(2016, 4, 1),
    bases: Sequence[str] = ("CONSOLIDATED", "STANDALONE"),
    integrated: bool = False,
) -> IngestResult:
    """`integrated=True` reads the SEBI integrated-filing feed (results from 2025 on); the default is the older feed."""
    res = IngestResult(symbol)
    url = (INTEGRATED_URL if integrated else LISTING_URL).format(symbol=symbol)
    raw = _fetch(get, url)
    lake.put(
        "nse",
        f"{'integrated_filing' if integrated else 'financial_results'}_{symbol}",
        now.date(),
        raw,
        url=url,
        fetched_at=now,
    )
    filings = (
        [f for f in parse_integrated_listing(raw) if f.symbol == symbol]
        if integrated
        else parse_listing(raw)
    )
    res.listed = len(filings)
    for f in sorted(filings, key=lambda x: (x.period_end, x.basis)):
        if f.period_end < since or f.basis not in bases:
            continue
        if (
            f.filed_at is None
        ):  # without an exact filing time a filing can never be used point-in-time
            res.note("NO_FILING_TIME")
        elif f.cumulative:
            note_unloaded(conn, f, "NOT_QUARTERLY", "cumulative filing", now)
            res.note("NOT_QUARTERLY")
        elif f.xbrl_url is None:
            note_unloaded(conn, f, "NO_XBRL_OLD_FORMAT", "NSE has no XBRL for this filing", now)
            res.note("NO_XBRL_OLD_FORMAT")
        elif conn.execute(
            "SELECT 1 FROM fundamental_filing WHERE symbol=%s AND seq_number=%s",
            (f.symbol, f.seq_number),
        ).fetchone():
            res.already += 1
        else:
            _load(conn, lake, get, f, now, res)
    return res


def _instrument(conn: psycopg.Connection, f: Filing) -> int | None:
    """By ISIN; else by the NSE symbol alias valid on the filing date (NSE's listing can carry a pre-split ISIN)."""
    row = conn.execute("SELECT instrument_id FROM instrument WHERE isin=%s", (f.isin,)).fetchone()
    if row is None and f.filed_at is not None:
        day = f.filed_at.date()
        row = conn.execute(
            "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND source_symbol=%s"
            " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
            (f.symbol, day, day),
        ).fetchone()
    return int(row[0]) if row else None


def _load(
    conn: psycopg.Connection,
    lake: LocalLake,
    get: Callable[[str], bytes],
    f: Filing,
    now: datetime,
    res: IngestResult,
) -> None:
    assert f.xbrl_url is not None
    dataset, day = f"results_xbrl_{f.symbol}", (f.filed_at or now).date()
    kept = [m for m in lake.versions("nse", dataset, day) if m.url == f.xbrl_url]
    if kept:  # downloaded in an earlier run: re-parse from the lake, no network
        manifest, raw = kept[-1], lake.get(kept[-1])
    else:
        try:
            raw = _fetch(get, f.xbrl_url)
        except Blocked:
            raise
        except Exception as e:
            note_unloaded(conn, f, "FETCH_FAILED", repr(e)[:300], now)
            res.note("FETCH_FAILED")
            return
        manifest = lake.put("nse", dataset, day, raw, url=f.xbrl_url, fetched_at=now)
    try:
        st = parse_xbrl(raw)
        if not f.isin:  # integrated listing: ISIN and bank flag come from the XBRL
            f = replace(f, isin=st.isin, bank="interest_earned" in st.quarter)
        iid = _instrument(conn, f)
        with conn.transaction():
            store_filing(conn, f, st, manifest.checksum, iid, now)
    except (XbrlError, FilingMismatch) as e:
        note_unloaded(conn, f, "UNPARSEABLE", str(e)[:300], now)
        res.note("UNPARSEABLE")
        return
    res.stored += 1


def backfill_facts(conn: psycopg.Connection, lake: LocalLake) -> int:
    """Re-read every stored filing's XBRL from the lake (no network) and add the full set of figures. Returns filings read."""
    done = 0
    for fid, symbol, url, filed in conn.execute(
        "SELECT filing_id, symbol, xbrl_url, filed_at FROM fundamental_filing ORDER BY filing_id"
    ).fetchall():
        kept = [
            m for m in lake.versions("nse", f"results_xbrl_{symbol}", filed.date()) if m.url == url
        ]
        if not kept:
            continue
        try:
            st = parse_xbrl(lake.get(kept[-1]))
        except XbrlError:
            continue
        with conn.transaction():
            store_extra(conn, fid, st)
        done += 1
    return done

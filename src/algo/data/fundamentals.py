# ruff: noqa: E501  (SQL statements and one-line mappings are kept readable)
"""Quarterly fundamentals: QoQ and YoY growth that is point-in-time safe.

Pure part: `latest_per_period` keeps, per company / basis / quarter, the latest filing known as of a date (so a
restatement only appears once it was filed); `growth_rows` pairs each quarter with the previous quarter and with the
same quarter a year earlier by period-end date, never by position. Growth off a zero or negative base is undefined and
is reported as such, not as a percentage. A figure is known only when the later of the two filings it uses was made.
Persistence part: a filing and its XBRL must agree on period and basis before anything is stored."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import psycopg

from algo.data.providers.nse_results import Filing, Statement


@dataclass(frozen=True)
class QuarterRow:
    symbol: str
    basis: str
    period_end: date
    filed_at: datetime
    metrics: Mapping[str, Decimal]


@dataclass(frozen=True)
class GrowthRow:
    symbol: str
    basis: str
    period_end: date
    filed_at: datetime
    metrics: Mapping[str, Decimal]
    prev_quarter_end: date | None
    prev_year_end: date | None
    qoq: Mapping[str, Decimal]
    yoy: Mapping[str, Decimal]
    base_not_positive_qoq: tuple[str, ...]
    base_not_positive_yoy: tuple[str, ...]
    known_at_qoq: datetime | None
    known_at_yoy: datetime | None

    @property
    def known_at(self) -> datetime:
        return max(
            t for t in (self.filed_at, self.known_at_qoq, self.known_at_yoy) if t is not None
        )


def latest_per_period(rows: Iterable[QuarterRow], as_of: datetime | None) -> list[QuarterRow]:
    best: dict[tuple[str, str, date], QuarterRow] = {}
    for r in rows:
        if as_of is not None and r.filed_at > as_of:
            continue
        k = (r.symbol, r.basis, r.period_end)
        if k not in best or r.filed_at > best[k].filed_at:
            best[k] = r
    return sorted(best.values(), key=lambda r: (r.symbol, r.basis, r.period_end))


def _with_proxy(m: Mapping[str, Decimal]) -> dict[str, Decimal]:
    out = dict(m)
    if all(k in m for k in ("revenue", "expenses", "finance_costs", "depreciation")):
        out["ebitda_proxy"] = m["revenue"] - (
            m["expenses"] - m["finance_costs"] - m["depreciation"]
        )
    return out


def _nearest(
    series: Sequence[QuarterRow], end: date, lo: int, hi: int, target: int
) -> QuarterRow | None:
    cands = [r for r in series if lo <= (end - r.period_end).days <= hi]
    return min(cands, key=lambda r: abs((end - r.period_end).days - target), default=None)


def _growth(
    cur: Mapping[str, Decimal], base: Mapping[str, Decimal]
) -> tuple[dict[str, Decimal], tuple[str, ...]]:
    out: dict[str, Decimal] = {}
    skipped = []
    for k, v in cur.items():
        if k in base:
            if base[k] > 0:
                out[k] = (v - base[k]) / base[k]
            else:
                skipped.append(k)
    return out, tuple(sorted(skipped))


def growth_rows(rows: Iterable[QuarterRow], as_of: datetime | None = None) -> list[GrowthRow]:
    groups: dict[tuple[str, str], list[QuarterRow]] = defaultdict(list)
    for r in latest_per_period(rows, as_of):
        groups[(r.symbol, r.basis)].append(
            QuarterRow(r.symbol, r.basis, r.period_end, r.filed_at, _with_proxy(r.metrics))
        )
    out = []
    for series in groups.values():
        for cur in series:
            pq = _nearest(series, cur.period_end, 80, 100, 91)
            py = _nearest(series, cur.period_end, 355, 375, 365)
            qoq, skip_q = _growth(cur.metrics, pq.metrics) if pq else ({}, ())
            yoy, skip_y = _growth(cur.metrics, py.metrics) if py else ({}, ())
            out.append(
                GrowthRow(
                    cur.symbol, cur.basis, cur.period_end, cur.filed_at, cur.metrics,
                    pq.period_end if pq else None, py.period_end if py else None, qoq, yoy, skip_q, skip_y,
                    max(cur.filed_at, pq.filed_at) if pq else None, max(cur.filed_at, py.filed_at) if py else None,
                )
            )  # fmt: skip
    return sorted(out, key=lambda r: (r.symbol, r.basis, r.period_end))


# ---------------------------------------------------------------- persistence


class FilingMismatch(Exception):
    pass


def store_filing(
    conn: psycopg.Connection,
    filing: Filing,
    st: Statement,
    raw_sha256: str,
    instrument_id: int | None,
    now: datetime,
) -> bool:
    """Store one filing and its facts. False if it was already stored. The listing and the XBRL must agree."""
    if filing.filed_at is None:
        raise FilingMismatch(
            f"{filing.symbol} {filing.seq_number}: no exact filing time, so it cannot be used point-in-time"
        )
    if (filing.period_end, filing.basis) != (st.period_end, st.basis):
        raise FilingMismatch(
            f"{filing.symbol} {filing.seq_number}: listing says {filing.period_end} {filing.basis}, XBRL says {st.period_end} {st.basis}"
        )
    row = conn.execute(
        "INSERT INTO fundamental_filing (symbol,isin,instrument_id,seq_number,period_start,period_end,basis,audited,bank,"
        "filed_at,rounding,xbrl_url,raw_sha256,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (symbol, seq_number) DO NOTHING RETURNING filing_id",
        (filing.symbol, filing.isin, instrument_id, filing.seq_number, st.period_start, st.period_end, st.basis,
         st.audited, filing.bank, filing.filed_at, st.rounding, filing.xbrl_url, raw_sha256, now),
    ).fetchone()  # fmt: skip
    if row is None:
        return False
    conn.cursor().executemany(
        "INSERT INTO fundamental_fact (filing_id, metric, scope, value) VALUES (%s,%s,%s,%s)",
        [(row[0], m, "QUARTER", v) for m, v in st.quarter.items()]
        + [(row[0], m, "YTD", v) for m, v in st.ytd.items()],
    )
    conn.execute(
        "DELETE FROM fundamental_unloaded WHERE symbol=%s AND seq_number=%s",
        (filing.symbol, filing.seq_number),
    )
    return True


def note_unloaded(
    conn: psycopg.Connection, filing: Filing, reason: str, detail: str, now: datetime
) -> None:
    assert filing.filed_at is not None  # callers skip filings without a filing time
    conn.execute(
        "INSERT INTO fundamental_unloaded (symbol,seq_number,period_end,basis,filed_at,reason,detail,detail_url,noted_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (symbol, seq_number) DO UPDATE SET reason=EXCLUDED.reason,"
        " detail=EXCLUDED.detail, noted_at=EXCLUDED.noted_at",
        (
            filing.symbol,
            filing.seq_number,
            filing.period_end,
            filing.basis,
            filing.filed_at,
            reason,
            detail,
            filing.detail_url,
            now,
        ),
    )


def load_quarter_rows(conn: psycopg.Connection) -> list[QuarterRow]:
    facts: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for fid, metric, value in conn.execute(
        "SELECT filing_id, metric, value FROM fundamental_fact WHERE scope='QUARTER'"
    ):
        facts[fid][metric] = value
    return [
        QuarterRow(sym, basis, end, filed, facts.get(fid, {}))
        for fid, sym, basis, end, filed in conn.execute(
            "SELECT filing_id, symbol, basis, period_end, filed_at FROM fundamental_filing ORDER BY symbol, basis, period_end, filed_at"
        )
    ]

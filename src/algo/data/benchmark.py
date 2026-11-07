"""Benchmark index series: immutable storage, strict date alignment, a pinned dataset hash.
Gate comparisons use TOTAL_RETURN (gross) series only: a price index omits dividends the strategy
earns, which would flatter the strategy."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc

RETURN_TYPES = ("PRICE", "TOTAL_RETURN", "NET_TOTAL_RETURN")


class BenchmarkError(Exception):
    pass


def aligned_returns(levels: Mapping[date, Decimal], days: Sequence[date]) -> list[float]:
    """Simple returns between consecutive `days` (the first day is the base). Every day must have a
    level: a missing date is an error, never skipped or interpolated."""
    missing = [d for d in days if d not in levels]
    if missing:
        raise BenchmarkError(f"benchmark has no level for {len(missing)} date(s): {missing[:5]}")
    if sorted(set(days)) != list(days):
        raise BenchmarkError("days must be strictly increasing")
    return [float(levels[b] / levels[a] - 1) for a, b in zip(days, days[1:], strict=False)]


def register(
    conn: psycopg.Connection, *, name: str, provider: str, index_symbol: str, return_type: str,
    methodology_version: str,
) -> int:  # fmt: skip
    if return_type not in RETURN_TYPES:
        raise BenchmarkError(f"return_type must be one of {RETURN_TYPES}")
    row = conn.execute(
        "INSERT INTO benchmark (name,provider,index_symbol,return_type,methodology_version)"
        " VALUES (%s,%s,%s,%s,%s) RETURNING benchmark_id",
        (name, provider, index_symbol, return_type, methodology_version),
    ).fetchone()
    assert row is not None
    return int(row[0])


def ingest(
    conn: psycopg.Connection, benchmark_id: int, rows: Sequence[tuple[date, Decimal]], *,
    source: str, source_timestamp: datetime, raw_hash: str, now: datetime,
) -> int:  # fmt: skip
    """Store new observations. Re-supplying an identical value is a no-op; a DIFFERENT value for a
    stored date is a conflict and rejects the whole batch (history is never silently rewritten)."""
    dates = [d for d, _ in rows]
    if len(set(dates)) != len(dates):
        raise BenchmarkError("duplicate dates in the batch")
    if any(v <= 0 for _, v in rows):
        raise BenchmarkError("index levels must be positive")
    stored: dict[date, Decimal] = dict(
        conn.execute(
            "SELECT observation_date, close_value FROM benchmark_observation WHERE benchmark_id=%s",
            (benchmark_id,),
        ).fetchall()
    )
    conflicts = [d for d, v in rows if d in stored and stored[d] != v]
    if conflicts:
        raise BenchmarkError(
            f"{len(conflicts)} stored value(s) differ from the batch: {conflicts[:5]}"
        )
    new = [(d, v) for d, v in rows if d not in stored]
    with conn.transaction():
        conn.cursor().executemany(
            "INSERT INTO benchmark_observation VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    benchmark_id,
                    d,
                    v,
                    source,
                    require_utc(source_timestamp),
                    require_utc(now),
                    raw_hash,
                )
                for d, v in new
            ],
        )
    return len(new)


def levels(
    conn: psycopg.Connection, benchmark_id: int, start: date | None = None, end: date | None = None
) -> dict[date, Decimal]:
    return dict(
        conn.execute(
            "SELECT observation_date, close_value FROM benchmark_observation WHERE benchmark_id=%s"
            " AND (%s::date IS NULL OR observation_date >= %s) AND (%s::date IS NULL OR"
            " observation_date <= %s) ORDER BY observation_date",
            (benchmark_id, start, start, end, end),
        ).fetchall()
    )


def missing_sessions(have: Mapping[date, Decimal], sessions: Sequence[date]) -> list[date]:
    return [d for d in sessions if d not in have]


def dataset_hash(conn: psycopg.Connection, benchmark_id: int) -> str:
    """Hash of the stored (date, level) series: pin it in every validation report."""
    h = hashlib.sha256()
    for d, v in levels(conn, benchmark_id).items():
        h.update(f"{d}|{v.normalize()}\n".encode())
    return h.hexdigest()


def _meta(conn: psycopg.Connection, benchmark_id: int) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT name, provider, index_symbol, return_type, methodology_version FROM benchmark"
        " WHERE benchmark_id=%s",
        (benchmark_id,),
    ).fetchone()
    if row is None:
        raise BenchmarkError(f"no benchmark {benchmark_id}")
    return tuple(row)


def references(conn: psycopg.Connection, benchmark_id: int) -> dict[str, Any]:
    name, provider, symbol, rtype, method = _meta(conn, benchmark_id)
    lv = levels(conn, benchmark_id)
    ds = sorted(lv)
    return {
        "benchmark_id": benchmark_id, "name": name, "provider": provider, "index_symbol": symbol,
        "return_type": rtype, "methodology_version": method, "observations": len(ds),
        "first": str(ds[0]) if ds else None, "last": str(ds[-1]) if ds else None,
        "dataset_hash": dataset_hash(conn, benchmark_id),
    }  # fmt: skip


def gate_returns(conn: psycopg.Connection, benchmark_id: int, days: Sequence[date]) -> list[float]:
    """Benchmark returns for validation gates: total-return series only, exact dates, no gaps."""
    rtype = _meta(conn, benchmark_id)[3]
    if rtype != "TOTAL_RETURN":
        raise BenchmarkError(
            f"{rtype} series cannot back a gate: use the gross TOTAL_RETURN series"
        )
    return aligned_returns(levels(conn, benchmark_id, days[0], days[-1]), days)


def store_validation(
    conn: psycopg.Connection, benchmark_id: int, *, report: dict[str, Any], passed: bool,
    normalized_sha256: str, factsheet_sha256: str | None, unresolved: list[str], now: datetime,
) -> int:  # fmt: skip
    """Record a validation report for the series AS STORED NOW (its dataset hash is taken here)."""
    _meta(conn, benchmark_id)  # raises for an unknown benchmark
    row = conn.execute(
        "INSERT INTO benchmark_validation (benchmark_id,created_at,dataset_hash,normalized_sha256,"
        "factsheet_sha256,passed,report,unresolved) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        " RETURNING validation_id",
        (benchmark_id, require_utc(now), dataset_hash(conn, benchmark_id), normalized_sha256,
         factsheet_sha256, passed, Jsonb(report), Jsonb(unresolved)),
    ).fetchone()  # fmt: skip
    assert row is not None
    return int(row[0])


def validated(conn: psycopg.Connection, benchmark_id: int) -> bool:
    """True only if the LATEST validation passed AND was made against the data as stored now (a
    changed series is not covered by an old report). Gates must not use a benchmark otherwise."""
    row = conn.execute(
        "SELECT passed, dataset_hash FROM benchmark_validation WHERE benchmark_id=%s"
        " ORDER BY validation_id DESC LIMIT 1",
        (benchmark_id,),
    ).fetchone()
    return bool(row and row[0] and row[1] == dataset_hash(conn, benchmark_id))

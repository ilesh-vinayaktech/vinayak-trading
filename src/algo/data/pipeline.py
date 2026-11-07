"""fetch -> store raw -> parse -> validate -> load (one transaction). Re-runs never duplicate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.bars import SPECS
from algo.data.lake import LocalLake
from algo.data.providers.base import DataProvider, NotPublishedError, ParseError
from algo.data.quality.checks import validity


@dataclass
class Result:
    status: str  # loaded | noop | quarantined
    dataset_version: int | None = None
    rows: int = 0
    issues: list[str] = field(default_factory=list)
    unknown_symbols: list[str] = field(default_factory=list)


def run_partition(
    conn: psycopg.Connection,
    lake: LocalLake,
    provider: DataProvider,
    dataset: str,
    d: date,
    now: datetime,
    ingest_kind: str = "initial",
) -> Result:
    now = require_utc(now)
    raw = provider.fetch(dataset, d)
    m = lake.put(provider.name, dataset, d, raw, url=provider.url(dataset, d),
                 fetched_at=now, ingest_kind=ingest_kind)  # fmt: skip

    def record(status: str, version: int | None, detail: dict[str, object]) -> None:
        conn.execute(
            "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,status,"
            "dataset_version,detail,at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (provider.name, dataset, d, m.version, m.checksum, status, version, Jsonb(detail), now),
        )

    try:
        bars = list(provider.parse(dataset, d, raw))
    except ParseError as e:
        record("quarantined", None, {"parse_error": str(e)})
        return Result("quarantined", issues=[str(e)])

    issues = validity(bars)
    if issues:
        record("quarantined", None, {"issues": issues})
        return Result("quarantined", issues=issues)

    with conn.transaction():
        last = conn.execute(
            "SELECT checksum, dataset_version FROM partition_load WHERE source=%s AND dataset=%s "
            "AND partition=%s AND status IN ('loaded','noop') ORDER BY id DESC LIMIT 1",
            (provider.name, dataset, d),
        ).fetchone()
        if last and last[0] == m.checksum:
            record("noop", last[1], {})
            return Result("noop", last[1])
        version = (last[1] if last else 0) + 1
        rows_ = conn.execute(
            "SELECT source_symbol, instrument_id FROM instrument_alias WHERE source=%s"
            " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
            (provider.name, d, d),
        ).fetchall()
        known: dict[str, int] = {r[0]: r[1] for r in rows_}
        unknown = sorted({b.symbol for b in bars} - known.keys())
        spec = SPECS[provider.freq(dataset)]
        cols = ["instrument_id", "ts", "open", "high", "low", "close", "volume", *spec.extras,
                "source", "dataset_version", "ingested_at"]  # fmt: skip
        sql = f"INSERT INTO {spec.table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})"
        rows = [
            (known[b.symbol], b.ts, b.open, b.high, b.low, b.close, b.volume,
             *(b.extra.get(c) for c in spec.extras), provider.name, version, now)
            for b in bars
            if b.symbol in known
        ]  # fmt: skip
        conn.cursor().executemany(sql, rows)
        n = len(rows)
        record("loaded", version, {"rows": n, "unknown_symbols": unknown})
    return Result("loaded", version, n, unknown_symbols=unknown)


RETRY_DAYS = 7  # a missing file this recent may just not be posted yet


def _done(conn: psycopg.Connection, source: str, dataset: str, d: date, now: datetime) -> bool:
    row = conn.execute(
        "SELECT 1 FROM partition_load WHERE source=%s AND dataset=%s AND partition=%s AND "
        "(status IN ('loaded','noop') OR (status='not_published' AND partition < %s)) LIMIT 1",
        (source, dataset, d, now.date() - timedelta(days=RETRY_DAYS)),
    ).fetchone()
    return row is not None


def backfill(
    conn: psycopg.Connection,
    lake: LocalLake,
    provider: DataProvider,
    dataset: str,
    start: date,
    end: date,
    now: datetime,
    *,
    is_trading_day: Callable[[date], bool] = lambda d: d.weekday() < 5,
    progress: Callable[[date, str], None] = lambda d, status: None,
) -> dict[str, int]:
    """Resumable: partitions already loaded / known-unpublished are skipped. A missing file is
    recorded as 'not_published' (holiday; an incident if the day should have traded)."""
    counts: dict[str, int] = {}
    d = start
    while d <= end:
        if is_trading_day(d) and not _done(conn, provider.name, dataset, d, now):
            try:
                status = run_partition(conn, lake, provider, dataset, d, now).status
            except NotPublishedError:
                conn.execute(
                    "INSERT INTO partition_load (source,dataset,partition,status,at) "
                    "VALUES (%s,%s,%s,'not_published',%s)",
                    (provider.name, dataset, d, now),
                )
                status = "not_published"
            counts[status] = counts.get(status, 0) + 1
            progress(d, status)
        d += timedelta(days=1)
    return counts

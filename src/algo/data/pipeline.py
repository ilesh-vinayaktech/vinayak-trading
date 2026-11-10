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


@dataclass(frozen=True)
class InstrumentLoad:
    day: date
    instrument_id: int
    status: str  # loaded | not_mapped | no_raw_file | partition_not_loaded | raw_changed_since_load
    rows: int = 0
    already_loaded: int = 0


def backfill_instruments(
    conn: psycopg.Connection,
    lake: LocalLake,
    provider: DataProvider,
    dataset: str,
    days: list[date],
    instrument_ids: set[int],
    now: datetime,
) -> list[InstrumentLoad]:
    """Load ONLY these instruments' bars from raw files already stored and already loaded for other
    instruments (an alias became known after the partition loaded). Never fetches. A day is
    refused unless its latest stored raw file is byte-identical (checksum) to the one the partition
    was loaded from, so the rows join the SAME dataset version. Re-runs add nothing. Each loaded
    day gets an audit row in partition_load (status noop, detail.kind = instrument_backfill)."""
    now = require_utc(now)
    out: list[InstrumentLoad] = []
    spec = SPECS[provider.freq(dataset)]
    cols = ["instrument_id", "ts", "open", "high", "low", "close", "volume", *spec.extras,
            "source", "dataset_version", "ingested_at"]  # fmt: skip
    sql = (f"INSERT INTO {spec.table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})"
           " ON CONFLICT DO NOTHING")  # fmt: skip
    for d in days:
        manifests = lake.versions(provider.name, dataset, d)
        if not manifests:
            out += [InstrumentLoad(d, i, "no_raw_file") for i in sorted(instrument_ids)]
            continue
        m = manifests[-1]
        last = conn.execute(
            "SELECT checksum, dataset_version FROM partition_load WHERE source=%s AND dataset=%s "
            "AND partition=%s AND status IN ('loaded','noop') ORDER BY id DESC LIMIT 1",
            (provider.name, dataset, d),
        ).fetchone()
        if last is None:
            out += [InstrumentLoad(d, i, "partition_not_loaded") for i in sorted(instrument_ids)]
            continue
        if last[0] != m.checksum:
            out += [InstrumentLoad(d, i, "raw_changed_since_load") for i in sorted(instrument_ids)]
            continue
        bars = list(provider.parse(dataset, d, lake.get(m)))
        known: dict[str, int] = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT source_symbol, instrument_id FROM instrument_alias WHERE source=%s"
                " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
                (provider.name, d, d),
            ).fetchall()
        }
        chosen = [b for b in bars if b.symbol in known and known[b.symbol] in instrument_ids]
        issues = validity(chosen)
        if issues:
            raise ValueError(f"{d}: {issues}")
        loaded_here: dict[int, int] = {}
        total = {i: 0 for i in instrument_ids}
        with conn.transaction():
            for b in chosen:
                iid = known[b.symbol]
                total[iid] += 1
                cur = conn.execute(sql, (iid, b.ts, b.open, b.high, b.low, b.close, b.volume,
                                         *(b.extra.get(c) for c in spec.extras), provider.name,
                                         last[1], now))  # fmt: skip
                loaded_here[iid] = loaded_here.get(iid, 0) + cur.rowcount
            if loaded_here and any(loaded_here.values()):
                conn.execute(
                    "INSERT INTO partition_load (source,dataset,partition,raw_version,checksum,"
                    "status,dataset_version,detail,at) VALUES (%s,%s,%s,%s,%s,'noop',%s,%s,%s)",
                    (provider.name, dataset, d, m.version, m.checksum, last[1],
                     Jsonb({"kind": "instrument_backfill", "instrument_ids": sorted(loaded_here),
                            "rows": sum(loaded_here.values()), "raw_sha256": m.checksum}), now),
                )  # fmt: skip
        for i in sorted(instrument_ids):
            n, t = loaded_here.get(i, 0), total[i]
            out.append(InstrumentLoad(d, i, "not_mapped" if t == 0 else "loaded", n, t - n))
    return out


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

# ruff: noqa: E501
"""Named, sealed data snapshots (TODO 2.4) and the DataAPI that serves only what one pinned.

A snapshot is created at a moment (`known_at`, default now): bars, corporate actions and human decisions ingested later
are invisible to it, whatever the provider corrects afterwards. It stores a hash of those inputs, the calendar's
fingerprint, the Kite freeze in force, the raw-file manifest and any extra pins the caller supplies (cost schedule,
strategy config, code commit). `verify` recomputes the hashes: data changed under a snapshot is named and refused.
Deviation from the TODO text: the pin is the ingestion moment plus a recomputed hash, not a row-by-row list of dataset
versions; a change to anything that existed at the cutoff is detected by the hash, anything newer is invisible."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.reader import BarReader, History

SOURCES = ("kite", "bhavcopy")


class SnapshotChanged(Exception):
    pass


class NotInSnapshot(Exception):
    pass


def _reader(
    source: str, cutoff: date | None, known_at: datetime, conn: psycopg.Connection
) -> BarReader:
    if source == "kite":
        return BarReader(conn, source="kite", publish_lag=timedelta(0), known_at=known_at)
    return BarReader(conn, known_at=known_at, cutoff=cutoff)


def _calendar_hash(conn: psycopg.Connection, at: datetime) -> str:
    sessions = conn.execute(
        "SELECT session_date, kind, start_time, end_time FROM market_session WHERE created_at <= %s"
        " ORDER BY session_date, kind, start_time",
        (at,),
    ).fetchall()
    holidays = conn.execute(
        "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status FROM partition_load"
        " WHERE at <= %s ORDER BY source, dataset, partition, id DESC)"
        " SELECT partition FROM l WHERE status='not_published' ORDER BY 1",
        (at,),
    ).fetchall()
    body = json.dumps([[str(c) for c in r] for r in sessions] + [[str(r[0])] for r in holidays])
    return hashlib.sha256(body.encode()).hexdigest()


def create(
    conn: psycopg.Connection,
    now: datetime,
    *,
    instruments: Sequence[int],
    note: str,
    price_source: str = "bhavcopy",
    price_cutoff: date | None = None,
    known_at: datetime | None = None,
    code_commit: str = "",
    pins: dict[str, Any] | None = None,
) -> UUID:
    if price_source not in SOURCES:
        raise ValueError(f"price_source must be one of {SOURCES}, got {price_source!r}")
    if price_cutoff is not None and price_source != "bhavcopy":
        raise ValueError("price_cutoff only applies with price_source='bhavcopy'")
    ids = sorted(set(instruments))
    if not ids:
        raise ValueError("a snapshot needs instruments")
    if not note.strip():
        raise ValueError("a snapshot needs a note")
    at = require_utc(known_at) if known_at is not None else require_utc(now)
    h = _reader(price_source, price_cutoff, at, conn).snapshot_hash(ids)
    assert h is not None
    fz = conn.execute(
        "SELECT freeze_id, through_date FROM data_freeze WHERE source='kite' AND taken_at <= %s"
        " ORDER BY taken_at DESC LIMIT 1",
        (at,),
    ).fetchone()
    all_pins = {
        **(pins or {}),
        "code_commit": code_commit,
        "calendar": _calendar_hash(conn, at),
        "freeze": None if fz is None else {"id": str(fz[0]), "through": fz[1].isoformat()},
    }
    row = conn.execute(
        "INSERT INTO data_snapshot (created_at, cutoff_time, price_source, price_cutoff, instrument_ids,"
        " snapshot_hash, pins, status, note) VALUES (%s,%s,%s,%s,%s,%s,%s,'sealed',%s) RETURNING snapshot_id",
        (require_utc(now), at, price_source, price_cutoff, ids, h, Jsonb(all_pins), note.strip()),
    ).fetchone()
    assert row is not None
    sid: UUID = row[0]
    conn.execute(
        "INSERT INTO snapshot_partition (snapshot_id, source, dataset, partition_date, load_id, raw_version,"
        " checksum, status, dataset_version) SELECT %s, source, dataset, partition, id, raw_version, checksum,"
        " status, dataset_version FROM (SELECT DISTINCT ON (source, dataset, partition) * FROM partition_load"
        " WHERE at <= %s ORDER BY source, dataset, partition, id DESC) l",
        (sid, at),
    )
    return sid


def get(conn: psycopg.Connection, snapshot_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT snapshot_id, created_at, cutoff_time, price_source, price_cutoff, instrument_ids, snapshot_hash,"
        " pins, status, note FROM data_snapshot WHERE snapshot_id=%s",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("snapshot_id", "created_at", "cutoff_time", "price_source", "price_cutoff", "instrument_ids",
            "snapshot_hash", "pins", "status", "note")  # fmt: skip
    out = dict(zip(keys, row, strict=True))
    out["partitions"] = [
        {"source": r[0], "dataset": r[1], "partition_date": r[2], "load_id": r[3], "raw_version": r[4],
         "checksum": r[5], "status": r[6], "dataset_version": r[7]}
        for r in conn.execute(
            "SELECT source, dataset, partition_date, load_id, raw_version, checksum, status, dataset_version"
            " FROM snapshot_partition WHERE snapshot_id=%s ORDER BY source, dataset, partition_date",
            (snapshot_id,),
        )
    ]  # fmt: skip
    return out


def verify(conn: psycopg.Connection, snapshot_id: UUID) -> list[str]:
    s = get(conn, snapshot_id)
    if s is None:
        raise ValueError(f"no such snapshot {snapshot_id}")
    problems = []
    reader = _reader(s["price_source"], s["price_cutoff"], s["cutoff_time"], conn)
    if reader.snapshot_hash(s["instrument_ids"]) != s["snapshot_hash"]:
        problems.append(
            "bars, actions or decisions of the pinned instruments changed since the snapshot"
        )
    if _calendar_hash(conn, s["cutoff_time"]) != s["pins"]["calendar"]:
        problems.append("the calendar as of the cutoff changed since the snapshot")
    return problems


_verify = verify  # DataAPI's own `verify` argument shadows the function inside __init__


class DataAPI:
    """Serves bars only for the snapshot's instruments, as the database held them at its cutoff."""

    def __init__(self, conn: psycopg.Connection, snapshot_id: UUID, *, verify: bool = True) -> None:
        s = get(conn, snapshot_id)
        if s is None:
            raise ValueError(f"no such snapshot {snapshot_id}")
        if verify:
            problems = _verify(conn, snapshot_id)
            if problems:
                raise SnapshotChanged(f"snapshot {snapshot_id} changed: " + "; ".join(problems))
        self.snapshot = s
        self.instruments: list[int] = list(s["instrument_ids"])
        self.reader = _reader(s["price_source"], s["price_cutoff"], s["cutoff_time"], conn)

    def history(
        self,
        instrument_id: int,
        start: date,
        end: date,
        *,
        adjust: str = "none",
        strict: bool = False,
    ) -> History:
        if instrument_id not in self.instruments:
            raise NotInSnapshot(
                f"instrument {instrument_id} is not in snapshot {self.snapshot['snapshot_id']}"
            )
        return self.reader.history(instrument_id, start, end, adjust=adjust, strict=strict)

    def ref(self) -> dict[str, str]:
        """What a result records to say which data it read."""
        return {
            "snapshot_id": str(self.snapshot["snapshot_id"]),
            "hash": self.snapshot["snapshot_hash"],
        }

# ruff: noqa: E501
"""Freeze a price source's daily history: record what it holds, prove later that it is unchanged.

`take` writes one snapshot (data_freeze) and, per instrument, its row count, first and last timestamp and a SHA-256 over every
row up to the freeze date (data_freeze_item). `verify` recomputes those and names each stock whose rows no longer match. The
database also refuses to insert Kite bars into a frozen instrument's frozen period (migration 041). Rows after the freeze
date are not part of the snapshot, so new days arrive normally; later corporate actions are applied by our own records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import psycopg

DATASET = "bar_1d"
UPTO = "ts < ((%s::date + 1)::timestamp AT TIME ZONE 'UTC')"  # every bar of the freeze date itself is included
CHECKSUMS = f"""
SELECT instrument_id, count(*), min(ts), max(ts),
       encode(sha256(convert_to(string_agg(format('%%s|%%s|%%s|%%s|%%s|%%s|%%s|%%s', ts, open, high, low, close, volume,
              coalesce(adjusted_through::text, ''), dataset_version), E'\\n' ORDER BY ts, dataset_version), 'UTF8')), 'hex')
FROM bar_1d WHERE source = %s AND {UPTO} {{only}}
GROUP BY instrument_id
"""


class FreezeError(ValueError):
    pass


def _checksums(
    conn: psycopg.Connection, source: str, through: date, only: list[int] | None = None
) -> dict[int, tuple[int, datetime, datetime, str]]:
    sql = CHECKSUMS.format(only="" if only is None else "AND instrument_id = ANY(%s)")
    args: tuple[Any, ...] = (source, through) if only is None else (source, through, only)
    return {int(r[0]): (int(r[1]), r[2], r[3], r[4]) for r in conn.execute(sql, args).fetchall()}


def take(conn: psycopg.Connection, source: str, through: date, now: datetime, note: str) -> UUID:
    """Freeze `source`'s daily bars up to and including `through`."""
    if not note.strip():
        raise FreezeError("say why in the note")
    if through > now.astimezone(UTC).date():
        raise FreezeError(f"{through} is in the future")
    if conn.execute(
        "SELECT 1 FROM data_freeze WHERE source=%s AND dataset=%s AND through_date=%s",
        (source, DATASET, through),
    ).fetchone():
        raise FreezeError(f"{source} is already frozen through {through}")
    sums = _checksums(conn, source, through)
    if not sums:
        raise FreezeError(f"no {source} bars on or before {through}")
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO data_freeze (source, dataset, through_date, instruments, total_rows, note, taken_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING freeze_id",
            (
                source,
                DATASET,
                through,
                len(sums),
                sum(v[0] for v in sums.values()),
                note.strip(),
                now,
            ),
        ).fetchone()
        assert row is not None
        freeze_id: UUID = row[0]
        for iid, (n, first, last, sha) in sorted(sums.items()):
            conn.execute(
                "INSERT INTO data_freeze_item (freeze_id, instrument_id, row_count, first_ts, last_ts, sha256) VALUES (%s,%s,%s,%s,%s,%s)",
                (freeze_id, iid, n, first, last, sha),
            )
    return freeze_id


def get(conn: psycopg.Connection, freeze_id: UUID) -> dict[str, Any] | None:
    head = conn.execute(
        "SELECT source, dataset, through_date, instruments, total_rows, note, taken_at FROM data_freeze WHERE freeze_id=%s",
        (freeze_id,),
    ).fetchone()
    if head is None:
        return None
    keys = ["source", "dataset", "through_date", "instruments", "total_rows", "note", "taken_at"]
    items = conn.execute(
        "SELECT instrument_id, row_count, first_ts, last_ts, sha256 FROM data_freeze_item WHERE freeze_id=%s ORDER BY instrument_id",
        (freeze_id,),
    ).fetchall()
    item_keys = ["instrument_id", "row_count", "first_ts", "last_ts", "sha256"]
    return {
        **dict(zip(keys, head, strict=True)),
        "items": [dict(zip(item_keys, i, strict=True)) for i in items],
    }


def verify(conn: psycopg.Connection, freeze_id: UUID) -> list[dict[str, Any]]:
    """The stocks whose frozen rows are no longer what was recorded; empty means the history is exactly as frozen."""
    frozen = get(conn, freeze_id)
    if frozen is None:
        raise FreezeError("no such freeze")
    now = _checksums(
        conn,
        frozen["source"],
        frozen["through_date"],
        [i["instrument_id"] for i in frozen["items"]],
    )
    problems = []
    for item in frozen["items"]:
        got = now.get(item["instrument_id"])
        if got is None or got[0] != item["row_count"]:
            problems.append(
                {
                    "instrument_id": item["instrument_id"],
                    "why": f"{item['row_count']} rows were frozen, {0 if got is None else got[0]} now",
                }
            )
        elif got[3] != item["sha256"]:
            problems.append({"instrument_id": item["instrument_id"], "why": "rows changed"})
    return problems

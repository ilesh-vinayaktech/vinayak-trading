# ruff: noqa: E501
"""The data identity of a study (docs/vti-phase1-spec.md work item B). `dataset_sha256` identifies the DATA inputs only; the study's own
`study_sha256` (experiment.study_sha256) identifies the whole study, including the code identity and `known_at`.

A study is registered with a `known_at`: its reader sees only what the database held at that moment (bars, corporate actions and
decisions ingested later are invisible), so a provider correction or a new review decision cannot change an old study's result.
The first run SEALS the dataset (`study_dataset`): the manifest of every input as of `known_at`. Every later run recomputes it and
refuses to go on if it differs (`DatasetChanged`): something was backdated or tampered with."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.data.snapshot import snapshot_hash
from algo.research.study import StudySpec


class DatasetChanged(Exception):
    pass


@dataclass(frozen=True)
class Dataset:
    manifest: Mapping[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.manifest, sort_keys=True, default=str).encode()
        ).hexdigest()


def _freeze_items_sha256(conn: psycopg.Connection, freeze_id: str) -> str:
    rows = conn.execute(
        "SELECT instrument_id, row_count, first_ts, last_ts, sha256 FROM data_freeze_item WHERE freeze_id=%s ORDER BY instrument_id",
        (freeze_id,),
    ).fetchall()
    return hashlib.sha256(json.dumps([list(map(str, r)) for r in rows]).encode()).hexdigest()


def build(
    conn: psycopg.Connection,
    spec: StudySpec,
    study: Mapping[str, Any],
    intervals: Sequence[Any],
    instruments: Sequence[int],
    start: date,
    end: date,
    known_at: datetime,
) -> Dataset:
    """Every data input of the study as of `known_at`, for the universe it just built."""
    ivs = sorted(
        (i.instrument_id, i.start.isoformat(), None if i.end is None else i.end.isoformat())
        for i in intervals
    )
    freeze = study["data_freeze"]
    return Dataset(
        {
            "price_source": "kite",
            "publish_lag_seconds": 0,
            "known_at": known_at.isoformat(),
            "freeze": {
                "id": str(freeze["id"]),
                "through": freeze["through"],
                "items_sha256": _freeze_items_sha256(conn, str(freeze["id"])),
            },
            "data_hash": snapshot_hash(conn, "kite", list(instruments), known_at),
            "universe": {
                "spec": spec.universe.model_dump(mode="json"),
                "membership_sha256": hashlib.sha256(json.dumps(ivs).encode()).hexdigest(),
                "instruments": len(set(instruments)),
            },
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "cost_schedules": study["cost_schedules"],
        }
    )


def check(conn: psycopg.Connection, experiment_id: int, dataset: Dataset) -> str:
    """Seal the dataset on the first run; on every later run it must be identical. Returns `dataset_sha256`."""
    sha = dataset.sha256
    row = conn.execute(
        "SELECT dataset_sha256 FROM study_dataset WHERE experiment_id=%s", (experiment_id,)
    ).fetchone()
    if row is None:
        try:
            conn.execute(
                "INSERT INTO study_dataset (experiment_id, dataset_sha256, manifest, sealed_at) VALUES (%s,%s,%s,now())",
                (experiment_id, sha, Jsonb(dict(dataset.manifest))),
            )
        except (
            psycopg.errors.UniqueViolation
        ):  # another worker sealed it a moment ago: compare with theirs
            row = conn.execute(
                "SELECT dataset_sha256 FROM study_dataset WHERE experiment_id=%s", (experiment_id,)
            ).fetchone()
        else:
            return sha
    assert row is not None
    if row[0] != sha:
        raise DatasetChanged(
            f"the data this study was registered against has changed (sealed {row[0][:12]}, now {sha[:12]})"
        )
    return sha


def sealed(conn: psycopg.Connection, experiment_id: int) -> str | None:
    row = conn.execute(
        "SELECT dataset_sha256 FROM study_dataset WHERE experiment_id=%s", (experiment_id,)
    ).fetchone()
    return None if row is None else str(row[0])

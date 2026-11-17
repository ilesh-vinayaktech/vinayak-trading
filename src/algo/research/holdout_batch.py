# ruff: noqa: E501
"""Holdout batches (docs/holdout-policy-v3.md, which replaces the "one batch ever" rule of docs/vti-alignment.md section 3).

  * Batches are append-only and numbered by `batch_id`. What limits them is the lifetime budget of 30 candidate slots (`holdout_candidate`, enforced by
    a database trigger): `freeze` reserves a slot and commits a 128-bit bootstrap seed per candidate in the same transaction that stores the manifest.
  * States move forward only, enforced by a database trigger: REGISTERED -> FROZEN -> EVALUATING -> CONSUMED | EVALUATION_FAILED.
  * `freeze` validates the manifest (every candidate with its hashes, family and a PASSED development validation report; the window
    equal to the lock; the evaluator version) BEFORE any holdout data is read, then stores it immutably with its hash.
  * `evaluate` commits EVALUATING, then the durable first-read marker (which consumes the batch's slots for good), and only then hands the evaluator a
    one-use capability holding the unwrapped reader. A batch that fails before the marker releases its slots; after it they stay consumed. A crash leaves
    the batch EVALUATING; only the same manifest and evaluator version may resume it. Verdicts are written once, atomically, with the move to CONSUMED.
  * Research code can read only `read_verdicts`: PASS, FAIL, INSUFFICIENT_EVIDENCE or NOT_APPLICABLE per candidate and gate.
    The detailed report is stored for the owner and has no research-facing accessor.
Not here yet (policy section 10): the automatic cutoff and its snapshot, the minimum batch size, the capability-scoped evaluator with the Monte Carlo test, and the owner-only
access. The manifest carries family ids and trial counts as given."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.validation import mc_bootstrap
from algo.research import holdout_guard, holdout_lock
from algo.research.holdout_lock import HoldoutError, Lock

EVALUATOR_VERSION = "holdout-evaluator-1"
METHODOLOGY_VERSION = "holdout-v3.0"  # docs/holdout-policy-v3.md; the numpy version is recorded beside it in the manifest
BUDGET = 30  # candidate slots for the life of the dataset (policy section 3); the database enforces it too
VERDICTS = ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE")
_TOKEN = object()  # only this module can mint a Capability
_ADVISORY_KEY = 7_203_001  # one evaluation at a time, even across processes


class BatchError(HoldoutError):
    pass


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family_id: str
    strategy_version: str
    parameter_hash: str
    dataset_sha256: str
    study_sha256: str
    validation_report_id: int


@dataclass(frozen=True)
class Manifest:
    batch_id: int
    candidates: tuple[Candidate, ...]
    family_trials: Mapping[str, int]
    date_from: date
    date_to: date
    correction_method: str
    correction_version: str
    evaluator_version: str
    seeds: Mapping[str, str] = field(
        default_factory=dict
    )  # candidate_id -> 128-bit bootstrap seed (hex), drawn at freeze, never supplied by a caller
    methodology_version: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "candidates": [vars(c) for c in sorted(self.candidates, key=lambda c: c.candidate_id)],
            "family_trials": dict(sorted(self.family_trials.items())),
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "correction_method": self.correction_method,
            "correction_version": self.correction_version,
            "evaluator_version": self.evaluator_version,
            "seeds": dict(sorted(self.seeds.items())),
            "methodology_version": self.methodology_version,
        }

    @classmethod
    def from_json(cls, d: Mapping[str, Any]) -> Manifest:
        return cls(
            d["batch_id"],
            tuple(Candidate(**c) for c in d["candidates"]),
            dict(d["family_trials"]),
            date.fromisoformat(d["date_from"]),
            date.fromisoformat(d["date_to"]),
            d["correction_method"],
            d["correction_version"],
            d["evaluator_version"],
            dict(d.get("seeds", {})),
            d.get("methodology_version", ""),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Results:
    verdicts: Mapping[tuple[str, str], str]  # (candidate_id, gate) -> one of VERDICTS
    report: Mapping[str, Any]  # the detail, for the owner only


class Capability:
    """Holds the unwrapped reader for exactly one evaluation; unusable once it ends."""

    __slots__ = ("_connection", "_live", "_reader")

    def __init__(self, token: object, reader: Any, connection: Any = None) -> None:
        if token is not _TOKEN:
            raise BatchError("only the evaluator can create the holdout capability")
        self._reader, self._connection, self._live = reader, connection, True

    @property
    def reader(self) -> Any:
        if not self._live:
            raise BatchError("the holdout capability has been revoked")
        return self._reader

    @property
    def connection(self) -> Any:
        """The guarded handle (`holdout_guard`): the only way the evaluator reaches the database. Never a raw connection."""
        if not self._live:
            raise BatchError("the holdout capability has been revoked")
        return self._connection

    def _revoke(self) -> None:
        self._live = False


def manifest_problems(m: Manifest, lock: Lock, batch_id: int) -> list[str]:
    """Every reason this manifest cannot be accepted (pure: the database checks come in `freeze`)."""
    out: list[str] = []
    if m.batch_id != batch_id:
        out.append(f"the manifest is for another batch ({m.batch_id}), not {batch_id}")
    if not m.candidates:
        out.append("the manifest has no candidates")
    seen: set[str] = set()
    for c in m.candidates:
        if c.candidate_id in seen:
            out.append(f"candidate {c.candidate_id} appears twice")
        seen.add(c.candidate_id)
        for name in (
            "candidate_id",
            "family_id",
            "strategy_version",
            "parameter_hash",
            "dataset_sha256",
            "study_sha256",
        ):
            if not getattr(c, name):
                out.append(f"candidate {c.candidate_id or '?'} has an empty {name}")
    if (m.date_from, m.date_to) != (lock.holdout_start, lock.holdout_end):
        out.append(
            f"the evaluation dates {m.date_from}..{m.date_to} must equal the global holdout {lock.holdout_start}..{lock.holdout_end}"
        )
    if m.seeds or m.methodology_version:
        out.append("seeds and the methodology version are set by the freeze, never supplied")
    if m.evaluator_version != EVALUATOR_VERSION:
        out.append(f"the evaluator version {m.evaluator_version!r} is not {EVALUATOR_VERSION!r}")
    if not m.correction_method or not m.correction_version:
        out.append("the multiple-testing correction needs a method and a version")
    per_family: dict[str, int] = {}
    for c in m.candidates:
        per_family[c.family_id] = per_family.get(c.family_id, 0) + 1
    for family, n in per_family.items():
        if family not in m.family_trials:
            out.append(f"no trial count for family {family}")
        elif m.family_trials[family] < n:
            out.append(
                f"family {family} has fewer trials ({m.family_trials[family]}) than candidates ({n})"
            )
    return out


def check_results(m: Manifest, r: Results) -> None:
    ids = {c.candidate_id for c in m.candidates}
    covered = set()
    for (candidate, gate), verdict in r.verdicts.items():
        if candidate not in ids:
            raise BatchError(f"a verdict for {candidate}, which is not in the manifest")
        if not gate:
            raise BatchError(f"an empty gate name for candidate {candidate}")
        if verdict not in VERDICTS:
            raise BatchError(f"unknown verdict {verdict!r} for {candidate} / {gate}")
        covered.add(candidate)
    for c in sorted(ids - covered):
        raise BatchError(f"no verdict for candidate {c}")


def _commit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        conn.commit()


def _row(conn: psycopg.Connection, batch_id: int) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT state, lock_id, evaluator_version, manifest, manifest_sha256 FROM holdout_batch WHERE batch_id=%s",
        (batch_id,),
    ).fetchone()
    if row is None:
        raise BatchError(f"no holdout batch {batch_id}")
    return tuple(row)


def register(conn: psycopg.Connection, *, by: str, now: datetime) -> int:
    """Open a batch. Batches are append-only; what limits them is the slot budget at freeze."""
    holdout_lock.require(conn)  # fails closed
    newest = conn.execute(
        "SELECT lock_id FROM research_lock ORDER BY lock_id DESC LIMIT 1"
    ).fetchone()
    assert newest is not None  # require() found one
    row = conn.execute(
        "INSERT INTO holdout_batch (state, lock_id, evaluator_version, registered_by, registered_at)"
        " VALUES ('REGISTERED', %s, %s, %s, %s) RETURNING batch_id",
        (newest[0], EVALUATOR_VERSION, by, now),
    ).fetchone()
    assert row is not None
    return int(row[0])


def freeze(conn: psycopg.Connection, batch_id: int, m: Manifest, now: datetime) -> str:
    """Validate the manifest against the lock and the development evidence, then store it immutably. Returns its hash."""
    state, lock_id, _, _, _ = _row(conn, batch_id)
    if state != "REGISTERED":
        raise BatchError(f"the batch is {state}, not REGISTERED: its manifest cannot be set again")
    lock = holdout_lock.require(conn)
    newest = conn.execute(
        "SELECT lock_id FROM research_lock ORDER BY lock_id DESC LIMIT 1"
    ).fetchone()
    problems = manifest_problems(m, lock, batch_id)
    if newest is None or newest[0] != lock_id:
        problems.append("the research lock in force is not the one this batch was registered under")
    for c in m.candidates:
        study = conn.execute(
            "SELECT e.experiment_id, e.study, d.dataset_sha256 FROM experiment e"
            " LEFT JOIN study_dataset d USING (experiment_id)"
            " WHERE e.study_sha256=%s ORDER BY e.experiment_id LIMIT 1",
            (c.study_sha256,),
        ).fetchone()
        if study is None:
            problems.append(
                f"candidate {c.candidate_id}: no registered study has study_sha256 {c.study_sha256}"
            )
            continue
        code = (study[1] or {}).get("code") or {}
        if code.get("dirty", True):
            problems.append(
                f"candidate {c.candidate_id}: its study was registered from source that differs from its commit, so it cannot be reproduced"
            )
        if study[2] != c.dataset_sha256:
            problems.append(
                f"candidate {c.candidate_id}: dataset_sha256 does not match the dataset its study sealed"
            )
        ok = conn.execute(
            "SELECT passed, experiment_id FROM validation_report WHERE report_id=%s",
            (c.validation_report_id,),
        ).fetchone()
        if ok is None or not ok[0] or ok[1] != study[0]:
            problems.append(
                f"candidate {c.candidate_id} has no passed development validation report ({c.validation_report_id}) for its study"
            )
    if problems:
        raise BatchError("the manifest is refused: " + "; ".join(problems))
    m = replace(
        m,
        seeds={c.candidate_id: f"{mc_bootstrap.new_seed():032x}" for c in m.candidates},
        methodology_version=f"{METHODOLOGY_VERSION}/numpy-{np.__version__}",
    )
    sha = m.sha256
    try:
        with (
            conn.transaction()
        ):  # the slots, the seeds and the manifest become durable together or not at all
            for c in m.candidates:
                conn.execute(
                    "INSERT INTO holdout_candidate (batch_id, candidate_id, state, seed, reserved_at) VALUES (%s,%s,'RESERVED',%s,%s)",
                    (batch_id, c.candidate_id, m.seeds[c.candidate_id], now),
                )
            conn.execute(
                "UPDATE holdout_batch SET state='FROZEN', manifest=%s, manifest_sha256=%s, methodology_version=%s, frozen_at=%s WHERE batch_id=%s",
                (Jsonb(m.to_json()), sha, m.methodology_version, now, batch_id),
            )
    except (psycopg.errors.RaiseException, psycopg.errors.UniqueViolation) as e:
        raise BatchError(f"the batch cannot be frozen: {e}") from e
    return sha


def evaluate(
    conn: psycopg.Connection,
    batch_id: int,
    run: Callable[[Capability, Manifest], Results],
    reader_factory: Callable[[Any], Any],
    now: datetime,
) -> None:
    """Run the one evaluation (or resume an interrupted one with the same manifest and evaluator version)."""
    state, lock_id, version, manifest_json, sha = _row(conn, batch_id)
    holdout_lock.require(conn)
    if state not in ("FROZEN", "EVALUATING"):
        raise BatchError(f"the batch is {state}: it cannot be evaluated")
    manifest = Manifest.from_json(manifest_json)
    if version != EVALUATOR_VERSION or manifest.evaluator_version != EVALUATOR_VERSION:
        raise BatchError(
            f"the evaluator version is not the one this batch was registered with ({version}): it cannot be resumed"
        )
    if manifest.sha256 != sha:
        raise BatchError(
            "the stored manifest no longer matches its hash: the evaluation is refused"
        )
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_KEY,)).fetchone()
    if not got or not got[0]:
        raise BatchError("the holdout is already being evaluated")
    try:
        if state == "FROZEN":
            with conn.transaction():
                moved = conn.execute(
                    "UPDATE holdout_batch SET state='EVALUATING', evaluating_at=%s WHERE batch_id=%s AND state='FROZEN'",
                    (now, batch_id),
                ).rowcount
            if not moved:
                raise BatchError("the batch was started by someone else")
            _commit(conn)  # durable BEFORE the evaluator can read a single holdout day
        mark_first_read(
            conn, batch_id, now
        )  # durable BEFORE the reader exists: from here the batch's slots are consumed for good
        guarded = holdout_guard.guard(conn)  # exists only now, after the marker
        cap = Capability(_TOKEN, reader_factory(guarded), guarded)
        try:
            results = run(cap, manifest)
        finally:
            cap._revoke()
        check_results(manifest, results)
        with conn.transaction():
            for (candidate, gate), verdict in sorted(results.verdicts.items()):
                conn.execute(
                    "INSERT INTO holdout_verdict (batch_id, candidate_id, gate, verdict) VALUES (%s,%s,%s,%s)",
                    (batch_id, candidate, gate, verdict),
                )
            conn.execute(
                "INSERT INTO holdout_report (batch_id, report) VALUES (%s,%s)",
                (batch_id, Jsonb(dict(results.report))),
            )
            conn.execute(
                "UPDATE holdout_batch SET state='CONSUMED', finished_at=%s WHERE batch_id=%s",
                (now, batch_id),
            )
        _commit(conn)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_KEY,))


def supplement(
    conn: psycopg.Connection,
    batch_id: int,
    run: Callable[[Capability, Manifest], Results],
    reader_factory: Callable[[Any], Any],
    now: datetime,
) -> int:
    """Complete, once more, the checks of a CONSUMED batch that had no evidence (the index lacked a day): the same evaluator, manifest and committed seeds.
    Only a PASS or FAIL for a check that was INSUFFICIENT_EVIDENCE is recorded, in its own table; no verdict is changed and no slot is spent. Returns how many were recorded."""
    state, _, version, manifest_json, sha = _row(conn, batch_id)
    holdout_lock.require(conn)
    if state != "CONSUMED":
        raise BatchError(f"the batch is {state}: only a consumed batch has checks to complete")
    manifest = Manifest.from_json(manifest_json)
    if version != EVALUATOR_VERSION or manifest.sha256 != sha:
        raise BatchError("the evaluator or the stored manifest changed: the supplement is refused")
    got = conn.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_KEY,)).fetchone()
    if not got or not got[0]:
        raise BatchError("the holdout is already being evaluated")
    try:
        guarded = holdout_guard.guard(conn)
        cap = Capability(_TOKEN, reader_factory(guarded), guarded)
        try:
            results = run(cap, manifest)
        finally:
            cap._revoke()
        check_results(manifest, results)
        open_ = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT candidate_id, gate FROM holdout_verdict WHERE batch_id=%s AND verdict='INSUFFICIENT_EVIDENCE'",
                (batch_id,),
            ).fetchall()
        }
        done = 0
        with conn.transaction():
            for (candidate, gate), verdict in sorted(results.verdicts.items()):
                if (candidate, gate) in open_ and verdict in ("PASS", "FAIL"):
                    done += conn.execute(
                        "INSERT INTO holdout_supplement (batch_id, candidate_id, gate, verdict, recorded_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (batch_id, candidate, gate, verdict, now),
                    ).rowcount
        _commit(conn)
        return done
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_KEY,))


def mark_first_read(conn: psycopg.Connection, batch_id: int, now: datetime) -> None:
    """Commit the first-read marker (once; a resume finds it already there). It consumes every reserved slot of the batch."""
    with conn.transaction():
        conn.execute(
            "UPDATE holdout_batch SET first_read_at=%s WHERE batch_id=%s AND state='EVALUATING' AND first_read_at IS NULL",
            (now, batch_id),
        )
    _commit(conn)


def slots(conn: psycopg.Connection) -> tuple[int, int, int]:
    """(consumed, reserved, left) of the lifetime budget, from the ledger."""
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE state='CONSUMED'), count(*) FILTER (WHERE state='RESERVED') FROM holdout_candidate"
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), BUDGET - int(row[0]) - int(row[1])


def fail(conn: psycopg.Connection, batch_id: int, reason: str, now: datetime) -> None:
    """End an evaluation that cannot be recovered deterministically. The holdout stays consumed; nothing can be re-run."""
    with conn.transaction():
        moved = conn.execute(
            "UPDATE holdout_batch SET state='EVALUATION_FAILED', failure=%s, finished_at=%s WHERE batch_id=%s AND state='EVALUATING'",
            (reason, now, batch_id),
        ).rowcount
    if not moved:
        raise BatchError("the batch is not being evaluated: only an EVALUATING batch can fail")
    _commit(conn)

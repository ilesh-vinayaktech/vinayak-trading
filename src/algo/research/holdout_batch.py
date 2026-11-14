# ruff: noqa: E501
"""The one global holdout evaluation (docs/vti-alignment.md section 3, docs/vti-phase1-spec.md work item A, slice 2).

  * ONE batch ever (`holdout_batch.only_one` is unique): once registered, no other batch can be, in any state.
  * States move forward only, enforced by a database trigger: REGISTERED -> FROZEN -> EVALUATING -> CONSUMED | EVALUATION_FAILED.
  * `freeze` validates the manifest (every candidate with its hashes, family and a PASSED development validation report; the window
    equal to the lock; the evaluator version) BEFORE any holdout data is read, then stores it immutably with its hash.
  * `evaluate` commits EVALUATING first (the holdout counts as consumed from then on), only then hands the evaluator a one-use
    capability holding the unwrapped reader. A crash leaves the batch EVALUATING with nothing exposed; only the same manifest and
    evaluator version may resume it. Verdicts are written once, atomically, with the move to CONSUMED. `fail` ends a batch whose
    recovery is impossible: the holdout stays consumed and nothing may be re-run with changed inputs.
  * Research code can read only `read_verdicts`: PASS, FAIL, INSUFFICIENT_EVIDENCE or NOT_APPLICABLE per candidate and gate.
    The detailed report is stored for the owner and has no research-facing accessor.
Not here yet: the evaluator itself (running the frozen candidates over the holdout and judging the gates), and a family id that the
trial counter enforces (the manifest carries family ids and trial counts as given)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.research import holdout_lock
from algo.research.holdout_lock import HoldoutError, Lock

EVALUATOR_VERSION = "holdout-evaluator-1"
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

    __slots__ = ("_live", "_reader")

    def __init__(self, token: object, reader: Any) -> None:
        if token is not _TOKEN:
            raise BatchError("only the evaluator can create the holdout capability")
        self._reader, self._live = reader, True

    @property
    def reader(self) -> Any:
        if not self._live:
            raise BatchError("the holdout capability has been revoked")
        return self._reader

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
    """Reserve the one holdout batch. Refused, in every later state too, when a batch already exists."""
    holdout_lock.require(conn)  # fails closed
    newest = conn.execute(
        "SELECT lock_id FROM research_lock ORDER BY lock_id DESC LIMIT 1"
    ).fetchone()
    assert newest is not None  # require() found one
    try:
        row = conn.execute(
            "INSERT INTO holdout_batch (state, lock_id, evaluator_version, registered_by, registered_at)"
            " VALUES ('REGISTERED', %s, %s, %s, %s) RETURNING batch_id",
            (newest[0], EVALUATOR_VERSION, by, now),
        ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        raise BatchError(
            "cannot register: a holdout batch already exists (there is at most one, ever)"
        ) from e
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
    sha = m.sha256
    conn.execute(
        "UPDATE holdout_batch SET state='FROZEN', manifest=%s, manifest_sha256=%s, frozen_at=%s WHERE batch_id=%s",
        (Jsonb(m.to_json()), sha, now, batch_id),
    )
    return sha


def evaluate(
    conn: psycopg.Connection,
    batch_id: int,
    run: Callable[[Capability, Manifest], Results],
    reader_factory: Callable[[], Any],
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
        cap = Capability(_TOKEN, reader_factory())
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


def read_verdicts(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    """The only thing research code may read of the evaluation: (candidate, gate, verdict), once the batch is CONSUMED."""
    rows = conn.execute(
        "SELECT v.candidate_id, v.gate, v.verdict FROM holdout_verdict v JOIN holdout_batch b USING (batch_id)"
        " WHERE b.state='CONSUMED' ORDER BY 1, 2"
    ).fetchall()
    if not rows:
        raise BatchError("no consumed holdout batch: there are no verdicts to read")
    return [(r[0], r[1], r[2]) for r in rows]


def promotable(conn: psycopg.Connection, candidate_id: str) -> bool:
    """Every verdict PASS or NOT_APPLICABLE and at least one PASS. Insufficient evidence is never a weak pass."""
    got = {v for c, _, v in read_verdicts(conn) if c == candidate_id}
    return bool(got) and got <= {"PASS", "NOT_APPLICABLE"} and "PASS" in got

# ruff: noqa: E501
"""Holdout policy v3 sections 3 and 4: the automatic cutoff, its immutable snapshot, mechanical batch membership and the minimum batch size.

Two separate events, in this order. (1) The cutoff fires by itself when every definition's fixed-setting study has reached a terminal state; it records, once, who was
in the population with each development verdict, registration time and provenance status. Nobody supplies a list, delays it or changes it afterwards. (2) The batch is frozen
later, only when the provenance audit is signed: membership is every candidate of the snapshot whose development verdict passed and whose provenance is ELIGIBLE. Nobody
chooses among them; an INELIGIBLE one is excluded with reason 3; fewer than 3 carry over to the next cutoff (decision D2: the last batch may be smaller only when it uses the
entire remaining budget)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.live.market_calendar import windows_for
from algo.research import holdout_batch, holdout_evaluator

MIN_BATCH = 3
TERMINAL = ("DONE", "FAILED", "CANCELLED")
EXCLUSION_REASON_INELIGIBLE = (
    3  # policy section 3: ineligibility under section 4 (provenance or independence failure)
)


class CutoffError(holdout_batch.BatchError):
    pass


def _fixed_study(conn: psycopg.Connection, strategy_id: str, version: int) -> int | None:
    """The newest fixed-setting (single-configuration) study of a definition."""
    row = conn.execute(
        "SELECT experiment_id FROM experiment WHERE strategy_id='dsl'"
        " AND study->'spec'->'definition'->>'strategy_id'=%s AND (study->'spec'->'definition'->>'version')::int=%s"
        " AND study->'spec'->'fixed' IS NOT NULL AND study->'spec'->'fixed' <> 'null'::jsonb ORDER BY experiment_id DESC LIMIT 1",
        (strategy_id, version),
    ).fetchone()
    return None if row is None else int(row[0])


def _verdict_state(conn: psycopg.Connection, experiment_id: int) -> tuple[bool, str]:
    """(terminal, 'PASSED' | 'FAILED' | 'NO_VERDICT'): the latest verdict run's end and the newest development report."""
    run = conn.execute(
        "SELECT status FROM study_run WHERE experiment_id=%s AND kind='verdict' ORDER BY run_id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if run is None or run[0] not in TERMINAL:
        return False, "NO_VERDICT"
    rep = conn.execute(
        "SELECT passed FROM validation_report WHERE experiment_id=%s ORDER BY report_id DESC LIMIT 1",
        (experiment_id,),
    ).fetchone()
    if rep is None or run[0] != "DONE":
        return (
            True,
            "NO_VERDICT",
        )  # a run that ended without a verdict has no passed verdict and is simply not a member
    return True, "PASSED" if rep[0] else "FAILED"


def provenance(conn: psycopg.Connection, candidate_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status, reason FROM holdout_provenance WHERE candidate_id=%s ORDER BY provenance_id DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()
    return (row[0], row[1]) if row else ("PROVISIONAL", "no provenance recorded yet")


def round_complete(conn: psycopg.Connection) -> bool:
    """Every registered definition has a fixed-setting study whose verdict run reached a terminal state."""
    defs = conn.execute("SELECT strategy_id, version FROM strategy_definition").fetchall()
    if not defs:
        return False
    for sid, ver in defs:
        exp = _fixed_study(conn, sid, ver)
        if exp is None or not _verdict_state(conn, exp)[0]:
            return False
    return True


def snapshot(conn: psycopg.Connection) -> dict[str, Any]:
    """The candidate population as it stands: every definition with its study, development verdict, registration time, provenance status and slot state."""
    out = []
    for sid, ver, created in conn.execute(
        "SELECT strategy_id, version, created_at FROM strategy_definition ORDER BY strategy_id, version"
    ).fetchall():
        cid = f"{sid}@{ver}"
        exp = _fixed_study(conn, sid, ver)
        verdict = _verdict_state(conn, exp)[1] if exp is not None else "NO_VERDICT"
        slot = conn.execute(
            "SELECT state FROM holdout_candidate WHERE candidate_id = ANY(%s) AND state IN ('RESERVED','CONSUMED') LIMIT 1",
            ([f"study-{exp}"],),
        ).fetchone()
        excluded = conn.execute(
            "SELECT reason FROM holdout_exclusion WHERE candidate_id=%s", (cid,)
        ).fetchone()
        status, why = provenance(conn, cid)
        out.append(
            {
                "candidate_id": cid, "experiment_id": exp, "development_verdict": verdict, "registered_at": created.isoformat(),
                "provenance": status, "provenance_reason": why, "slot": slot[0] if slot else None, "excluded_reason": excluded[0] if excluded else None,
            }
        )  # fmt: skip
    return {"candidates": out}


def _sha(snap: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()


def fire_batch1(conn: psycopg.Connection, now: datetime) -> int | None:
    """Fire the Batch 1 cutoff if (and only if) it has not fired and the round is complete. Returns its id, or None. Takes no list: the population is read from the database."""
    if conn.execute(
        "SELECT 1 FROM holdout_cutoff WHERE kind='BATCH1'"
    ).fetchone() or not round_complete(conn):
        return None
    snap = snapshot(conn)
    row = conn.execute(
        "INSERT INTO holdout_cutoff (kind, due_on, fired_at, snapshot, snapshot_sha256) VALUES ('BATCH1', NULL, %s, %s, %s) RETURNING cutoff_id",
        (now, Jsonb(snap), _sha(snap)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def fire_quarter(conn: psycopg.Connection, due_on: date, now: datetime) -> int | None:
    """Fire the calendar cutoff `due_on` (the last trading day of a quarter) once its date has come. The date is not chosen by the owner: it is a fixed calendar date."""
    if (
        now.date() < due_on
        or conn.execute(
            "SELECT 1 FROM holdout_cutoff WHERE kind='QUARTER' AND due_on=%s", (due_on,)
        ).fetchone()
    ):
        return None
    snap = snapshot(conn)
    row = conn.execute(
        "INSERT INTO holdout_cutoff (kind, due_on, fired_at, snapshot, snapshot_sha256) VALUES ('QUARTER', %s, %s, %s, %s) RETURNING cutoff_id",
        (due_on, now, Jsonb(snap), _sha(snap)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def last_trading_day(conn: psycopg.Connection, month_end: date) -> date:
    """The last trading day on or before a quarter's last calendar day, from the platform's market calendar."""
    day = month_end
    while not windows_for(conn, day):
        day -= timedelta(days=1)
    return day


def quarter_dates(first_after: date, until: date) -> list[date]:
    """Quarter-end calendar days after `first_after` and up to `until` (the cutoffs are fixed calendar dates, never chosen)."""
    out = []
    for year in range(first_after.year, until.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = date(year, m, d)
            if first_after < q <= until + timedelta(days=7):
                out.append(q)
    return out


def fire_due_quarters(conn: psycopg.Connection, now: datetime) -> list[int]:
    """Fire every quarterly cutoff whose last trading day has come, once the Batch 1 cutoff exists. Nobody can delay one or trigger it early."""
    first = conn.execute("SELECT fired_at FROM holdout_cutoff WHERE kind='BATCH1'").fetchone()
    if first is None:
        return []
    fired = []
    for q in quarter_dates(first[0].date(), now.date()):
        cid = fire_quarter(conn, last_trading_day(conn, q), now)
        if cid is not None:
            fired.append(cid)
    return fired


def record_provenance(
    conn: psycopg.Connection, candidate_id: str, status: str, reason: str, now: datetime
) -> None:
    conn.execute(
        "INSERT INTO holdout_provenance (candidate_id, status, reason, recorded_at) VALUES (%s,%s,%s,%s)",
        (candidate_id, status, reason, now),
    )


def sign_audit(conn: psycopg.Connection, by: str, document: str, now: datetime) -> int:
    """The owner signs the procedure-provenance audit (policy section 4.1); `document` is its text, hashed."""
    row = conn.execute(
        "INSERT INTO holdout_audit (signed_by, signed_at, document, document_sha256) VALUES (%s,%s,%s,%s) RETURNING audit_id",
        (by, now, document, hashlib.sha256(document.encode()).hexdigest()),
    ).fetchone()
    assert row is not None
    return int(row[0])


@dataclass(frozen=True)
class Plan:
    members: tuple[str, ...] = ()
    experiments: dict[str, int] = field(default_factory=dict)
    carry_over: tuple[str, ...] = ()
    excluded: dict[str, str] = field(default_factory=dict)  # candidate_id -> evidence (reason 3)
    problems: tuple[str, ...] = ()  # why no batch can be frozen now

    @property
    def can_freeze(self) -> bool:
        return bool(self.members) and not self.problems


def plan(conn: psycopg.Connection, cutoff_id: int) -> Plan:
    """What the snapshot's candidates become, mechanically. Pure: it writes nothing."""
    row = conn.execute(
        "SELECT snapshot FROM holdout_cutoff WHERE cutoff_id=%s", (cutoff_id,)
    ).fetchone()
    if row is None:
        raise CutoffError(f"no cutoff {cutoff_id}")
    passed = [
        c
        for c in row[0]["candidates"]
        if c["development_verdict"] == "PASSED"
        and c["slot"] is None
        and c["excluded_reason"] is None
        and c["experiment_id"] is not None
    ]
    members, experiments, excluded = [], {}, {}
    for (
        c
    ) in passed:  # the audit's result applies to the snapshot's members only; it can never add one
        status, why = provenance(conn, c["candidate_id"])
        if status == "INELIGIBLE":
            excluded[c["candidate_id"]] = why
        elif status == "ELIGIBLE":
            members.append(c["candidate_id"])
            experiments[c["candidate_id"]] = c["experiment_id"]
    pending = [
        c["candidate_id"] for c in passed if provenance(conn, c["candidate_id"])[0] == "PROVISIONAL"
    ]
    problems: list[str] = []
    if conn.execute("SELECT 1 FROM holdout_audit LIMIT 1").fetchone() is None:
        problems.append("the provenance audit is not signed: the batch stays PENDING")
    if pending:
        problems.append(f"provenance not resolved for {', '.join(sorted(pending))}")
    left = holdout_batch.slots(conn)[2]
    if len(members) > left:
        problems.append(f"{len(members)} candidates do not fit the {left} slots left")
    elif members and len(members) < MIN_BATCH and len(members) != left:
        problems.append(
            f"fewer than {MIN_BATCH} candidates and not the last batch: they carry over to the next cutoff"
        )
    carry = tuple(members) if members and len(members) < MIN_BATCH and len(members) != left else ()
    return Plan(tuple(members), experiments, carry, excluded, tuple(problems))


def freeze_batch(conn: psycopg.Connection, cutoff_id: int, by: str, now: datetime) -> int | None:
    """Freeze the batch of this cutoff if its plan allows: record the reason-3 exclusions, open the batch, build the manifest from the registry and freeze it (seeds drawn and slots reserved there)."""
    p = plan(conn, cutoff_id)
    if not p.can_freeze:
        return None
    for cid, evidence in p.excluded.items():
        conn.execute(
            "INSERT INTO holdout_exclusion (candidate_id, reason, evidence, excluded_at) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (cid, EXCLUSION_REASON_INELIGIBLE, evidence, now),
        )
    batch_id = holdout_batch.register(conn, by=by, now=now)
    holdout_batch.freeze(
        conn,
        batch_id,
        holdout_evaluator.build_manifest(conn, batch_id, sorted(p.experiments.values())),
        now,
    )
    return batch_id

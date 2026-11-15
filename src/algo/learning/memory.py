# ruff: noqa: E501
"""Research memory (plan.md phase 4): a searchable, insert-only record of what was tried, what failed and why, and what was decided.

Callers: tests/integration/learning/test_memory.py. Schema: research_note (migration 081). User's instruction: "do as much as you can do yourself, keep taking
things one by one from @TODO.md and @plan.md ... keep things finishing with test".
  * Notes are never edited; a correction is a new note. Failures are kept as carefully as findings: they are what stops the same idea being retried blind.
  * `sync_alpha` turns every alpha hypothesis into a note once (REJECTED -> FAILURE, CANDIDATE -> FINDING), worded from the stored evidence, never typed by hand.
  * Search is plain: tag overlap, kind, subject prefix and a case-insensitive substring of subject or body (wildcards in the query are matched literally)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from algo.core.clock import require_utc

KINDS = ("FINDING", "FAILURE", "DECISION", "LESSON")


@dataclass(frozen=True)
class Note:
    note_id: int
    kind: str
    subject: str
    body: str
    tags: list[str]
    created_by: str
    created_at: datetime


def add(
    conn: psycopg.Connection,
    kind: str,
    subject: str,
    body: str,
    *,
    by: str,
    now: datetime,
    tags: Sequence[str] = (),
) -> int:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not subject.strip() or not body.strip() or not by.strip():
        raise ValueError("a note needs a subject, a body and an author")
    clean = sorted({t.strip().lower() for t in tags if t.strip()})
    row = conn.execute(
        "INSERT INTO research_note (kind, subject, body, tags, created_by, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING note_id",
        (kind, subject.strip(), body.strip(), clean, by.strip(), require_utc(now)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(
    conn: psycopg.Connection,
    *,
    text: str | None = None,
    tags: Sequence[str] = (),
    kind: str | None = None,
    subject_prefix: str | None = None,
    limit: int = 50,
) -> list[Note]:
    """Newest first. Every given filter must hold; tags need ALL of the tags given."""
    where: list[str] = ["TRUE"]
    args: list[Any] = []
    if text:
        where.append("(subject ILIKE %s OR body ILIKE %s)")
        args += [f"%{_escape(text)}%"] * 2
    if tags:
        where.append("tags @> %s")
        args.append(sorted({t.strip().lower() for t in tags}))
    if kind:
        where.append("kind = %s")
        args.append(kind)
    if subject_prefix:
        where.append("subject LIKE %s")
        args.append(f"{_escape(subject_prefix)}%")
    rows = conn.execute(
        f"SELECT note_id, kind, subject, body, tags, created_by, created_at FROM research_note WHERE {' AND '.join(where)} ORDER BY note_id DESC LIMIT %s",  # noqa: S608 - fixed fragments only
        (*args, limit),
    ).fetchall()
    return [Note(*r) for r in rows]


def sync_alpha(conn: psycopg.Connection, *, now: datetime) -> int:
    """One note per alpha hypothesis not yet noted; returns how many were written."""
    now = require_utc(now)
    rows = conn.execute(
        "SELECT hypothesis_id, feature_name, feature_version, horizon_days, research_status, evidence FROM alpha_hypothesis h"
        " WHERE NOT EXISTS (SELECT 1 FROM research_note n WHERE n.source_kind = 'alpha_hypothesis' AND n.source_id = h.hypothesis_id) ORDER BY hypothesis_id"
    ).fetchall()
    for hid, name, ver, horizon, status, ev in rows:
        kind = "FINDING" if status == "CANDIDATE" else "FAILURE"
        body = f"{name} v{ver} at {horizon} days was {status}: " + ", ".join(
            f"{k}={ev[k]}" for k in sorted(ev) if isinstance(ev[k], (int, float, str))
        )
        conn.execute(
            "INSERT INTO research_note (kind, subject, body, tags, source_kind, source_id, created_by, created_at) VALUES (%s,%s,%s,%s,'alpha_hypothesis',%s,'system',%s)",
            (
                kind,
                f"alpha:{name}:h{horizon}",
                body,
                sorted({"alpha", name.lower(), status.lower()}),
                hid,
                now,
            ),
        )
    return len(rows)

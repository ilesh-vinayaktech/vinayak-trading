"""Review queue: items come from a generated file, decisions are appended to `review_decision`.

The queue says what a person must decide and which choices exist; this module validates a decision
against that item's own options and appends it. It never changes identity, alias or membership
tables: applying a decision is a separate explicit step."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field

MAX_NOTE = 4000


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=60)
    reviewer: str = Field(min_length=1, max_length=80)
    effective_date: date | None = None
    effective_to: date | None = None
    evidence_ref: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=MAX_NOTE)


class ReviewError(Exception):
    pass


def load_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = json.loads(path.read_text())["items"]
    return items


def _latest(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT DISTINCT ON (item_id) item_id, decision_id, decision, effective_date, effective_to,"
        " evidence_ref, note, reviewer, decided_at FROM review_decision"
        " ORDER BY item_id, decision_id DESC"
    ).fetchall()
    return {
        r[0]: {"decision_id": r[1], "decision": r[2], "effective_date": r[3], "effective_to": r[4],
               "evidence_ref": r[5], "note": r[6], "reviewer": r[7], "decided_at": r[8]}
        for r in rows
    }  # fmt: skip


def listing(conn: psycopg.Connection, items: list[dict[str, Any]]) -> dict[str, Any]:
    latest = _latest(conn)
    out = [{**i, "latest": latest.get(i["id"])} for i in items]
    decided = sum(
        1 for i in out if i["latest"] and i["latest"]["decision"] != "NEEDS_MORE_EVIDENCE"
    )
    return {"items": out, "total": len(out), "decided": decided}


def history(conn: psycopg.Connection, item_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT decision_id, decision, effective_date, effective_to, evidence_ref, note, reviewer,"
        " decided_at FROM review_decision WHERE item_id=%s ORDER BY decision_id DESC",
        (item_id,),
    ).fetchall()
    keys = ("decision_id", "decision", "effective_date", "effective_to", "evidence_ref", "note",
            "reviewer", "decided_at")  # fmt: skip
    return [dict(zip(keys, r, strict=True)) for r in rows]


def record(
    conn: psycopg.Connection, item: dict[str, Any], d: DecisionIn, now: datetime
) -> int:  # fmt: skip
    opt = next((o for o in item["options"] if o["value"] == d.decision), None)
    if opt is None:
        raise ReviewError(f"{d.decision!r} is not an option for this item")
    if opt.get("needs_date") and d.effective_date is None:
        raise ReviewError("this decision needs an effective date")
    if not opt.get("needs_date") and (d.effective_date or d.effective_to):
        raise ReviewError("this decision takes no date")
    if d.effective_to and not opt.get("has_end"):
        raise ReviewError("this decision takes no end date")
    if opt.get("needs_evidence", True) and not d.evidence_ref.strip():
        raise ReviewError("cite the source document (evidence) for this decision")
    if d.effective_date and d.effective_to and d.effective_to < d.effective_date:
        raise ReviewError("the end date is before the start date")
    row = conn.execute(
        "INSERT INTO review_decision (item_id, decision, effective_date, effective_to,"
        " evidence_ref, note, reviewer, decided_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING decision_id",
        (
            item["id"],
            d.decision,
            d.effective_date,
            d.effective_to,
            d.evidence_ref.strip(),
            d.note.strip(),
            d.reviewer.strip(),
            now,
        ),
    ).fetchone()
    assert row is not None
    return int(row[0])

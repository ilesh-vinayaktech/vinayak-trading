# ruff: noqa: E501
"""Cost schedules kept in the database (table cost_schedule, migration 039) so they can be managed in the portal.

A schedule is stored as the same document that lives in config/cost_schedules/*.json, validated by the same
`schedule_from_dict`, so the calculator and the provenance rules (every component cites a source) are unchanged. What this
adds: importing the files once, adding a new version for a date range, a person verifying a schedule (recorded by name and
time), and extending current rates over earlier history as an explicit `assumed_backfill` that every run using it reports.
Schedules of one broker and product never overlap. A verified schedule cannot be removed or re-verified."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.backtest.costs.schedule import Schedule, ScheduleBook, ScheduleError, schedule_from_dict


def _doc(conn: psycopg.Connection, schedule_id: str, version: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT doc FROM cost_schedule WHERE schedule_id=%s AND version=%s", (schedule_id, version)
    ).fetchone()
    if row is None:
        raise ScheduleError(f"no such schedule: {schedule_id} {version}")
    doc: dict[str, Any] = row[0]
    return doc


def get(conn: psycopg.Connection, schedule_id: str, version: str) -> Schedule:
    return schedule_from_dict(_doc(conn, schedule_id, version))


def add(
    conn: psycopg.Connection, doc: Mapping[str, Any], *, actor: UUID | None, now: datetime
) -> Schedule:
    """Validate and store a schedule document. The same id and version with the same content is a no-op; with other
    content, or a range that overlaps another schedule of the broker and product, it is refused."""
    sch = schedule_from_dict(doc)
    existing = conn.execute(
        "SELECT doc_hash FROM cost_schedule WHERE schedule_id=%s AND version=%s",
        (sch.id, sch.version),
    ).fetchone()
    if existing is not None:
        if existing[0] == sch.doc_hash:
            return sch
        raise ScheduleError(f"a different document is already stored as {sch.id} {sch.version}")
    clash = conn.execute(
        "SELECT schedule_id FROM cost_schedule WHERE broker=%s AND product=%s AND valid_from <= COALESCE(%s::date, 'infinity'::date) AND COALESCE(valid_until, 'infinity'::date) >= %s",
        (sch.broker, sch.product, sch.valid_until, sch.valid_from),
    ).fetchone()
    if clash is not None:
        raise ScheduleError(f"{sch.id} overlaps {clash[0]} for {sch.broker} {sch.product}")
    conn.execute(
        "INSERT INTO cost_schedule (schedule_id, version, broker, product, valid_from, valid_until, status, verified_by, verified_at, doc, doc_hash, created_by, created_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            sch.id,
            sch.version,
            sch.broker,
            sch.product,
            sch.valid_from,
            sch.valid_until,
            sch.status,
            sch.verified_by,
            sch.verified_at,
            Jsonb(dict(doc)),
            sch.doc_hash,
            actor,
            now,
        ),
    )
    return sch


def import_files(conn: psycopg.Connection, directory: Path, *, now: datetime) -> int:
    """Seed the table from the JSON files; schedules already stored are left alone (never overwritten). Returns how many were new."""
    new = 0
    for f in sorted(directory.glob("*.json")):
        doc = json.loads(f.read_text())
        for entry in doc["schedules"] if "schedules" in doc else [doc]:
            known = conn.execute(
                "SELECT 1 FROM cost_schedule WHERE schedule_id=%s AND version=%s",
                (entry["id"], entry["version"]),
            ).fetchone()
            if known is None:
                add(conn, entry, actor=None, now=now)
                new += 1
    return new


def list_schedules(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT schedule_id, version, doc FROM cost_schedule ORDER BY broker, product, valid_from"
    ).fetchall()
    out = []
    for schedule_id, version, doc in rows:
        s = schedule_from_dict(doc)
        out.append(
            {
                "schedule_id": schedule_id,
                "version": version,
                "name": s.name,
                "broker": s.broker,
                "product": s.product,
                "valid_from": s.valid_from,
                "valid_until": s.valid_until,
                "status": s.status,
                "verified_by": s.verified_by,
                "verified_at": s.verified_at,
                "notes": s.notes,
                "assumptions": list(s.assumptions),
                "contract_note_min_brokerage": s.contract_note_min_brokerage,
                "components": [
                    {
                        "type": c.type,
                        "side": c.side.value,
                        "basis": c.basis.value,
                        "rate_pct": c.rate_pct,
                        "amount": c.amount,
                        "minimum": c.minimum,
                        "maximum": c.maximum,
                        "source": c.source,
                    }
                    for c in s.components
                ],
                "sources": [
                    {
                        "key": k,
                        "url": v.url,
                        "retrieved_at": v.retrieved_at,
                        "quote": v.quote,
                        "locator": v.locator,
                    }
                    for k, v in s.sources.items()
                ],
            }  # fmt: skip
        )
    return out


def verify(
    conn: psycopg.Connection,
    schedule_id: str,
    version: str,
    *,
    by: str,
    now: datetime,
    accept_assumptions: bool = False,
) -> Schedule:
    """A named person confirms the schedule against the sources it cites.

    A schedule that lists assumptions (what it takes on trust, such as a rate carried over a period no source covers) is
    verified only when the person also accepts them: the acceptance is recorded in the document, and the list stays with it."""
    row = conn.execute(
        "SELECT status, doc FROM cost_schedule WHERE schedule_id=%s AND version=%s FOR UPDATE",
        (schedule_id, version),
    ).fetchone()
    if row is None:
        raise ScheduleError(f"no such schedule: {schedule_id} {version}")
    if row[0] == "verified":
        raise ScheduleError("this schedule is already verified")
    if row[0] == "assumed_backfill":
        raise ScheduleError(
            "an assumed schedule is an assumption, so there is nothing to verify: verify the schedule it was copied from"
        )
    listed = schedule_from_dict(row[1]).assumptions
    if listed and not accept_assumptions:
        raise ScheduleError(
            f"accept the {len(listed)} assumption{'s' if len(listed) > 1 else ''} this schedule makes before verifying it"
        )
    doc = {**row[1], "status": "verified", "verified_by": by, "verified_at": now.isoformat()}
    if listed:
        doc["assumptions_accepted_by"] = by
    sch = schedule_from_dict(doc)
    conn.execute(
        "UPDATE cost_schedule SET status='verified', verified_by=%s, verified_at=%s, doc=%s, doc_hash=%s WHERE schedule_id=%s AND version=%s",
        (by, now, Jsonb(doc), sch.doc_hash, schedule_id, version),
    )
    return sch


def backfill(
    conn: psycopg.Connection,
    schedule_id: str,
    version: str,
    *,
    valid_from: date,
    actor: UUID | None,
    now: datetime,
) -> Schedule:
    """Extend a schedule's rates over the period before it, from `valid_from` to the day before it starts, as an assumption."""
    doc = _doc(conn, schedule_id, version)
    src = schedule_from_dict(doc)
    if valid_from >= src.valid_from:
        raise ScheduleError(f"the extension must start before {src.valid_from}")
    new = {
        **doc, "id": f"{schedule_id}-backfill-{valid_from}", "status": "assumed_backfill", "valid_from": str(valid_from),
        "valid_until": str(src.valid_from - timedelta(days=1)), "verified_by": None, "verified_at": None,
        "notes": f"The rates of {schedule_id} extended back to {valid_from} by an owner decision: not evidenced for this period.",
    }  # fmt: skip
    return add(conn, new, actor=actor, now=now)


def add_version(
    conn: psycopg.Connection,
    schedule_id: str,
    version: str,
    *,
    valid_from: date,
    valid_until: date | None,
    changes: Sequence[Mapping[str, Any]],
    note: str,
    by: str,
    actor: UUID | None,
    now: datetime,
) -> Schedule:
    """A price change: copy a schedule, change some component rates, and start it on `valid_from`. The changed components cite
    the person's note as their source (provenance "owner-entered"); the new version is unverified until a person verifies it.
    The open-ended schedule in force is ended the day before, in the same transaction, so a refusal changes nothing."""
    doc = _doc(conn, schedule_id, version)
    src = schedule_from_dict(doc)
    if valid_from <= src.valid_from:
        raise ScheduleError(f"a new version must start after {src.valid_from}, not before it")
    components = [dict(c) for c in doc["components"]]
    quote = note.strip() or f"entered by {by}"
    sources = {
        **doc["sources"],
        "owner_entered": {
            "url": "owner-entered",
            "retrieved_at": now.isoformat(),
            "sha256": hashlib.sha256(quote.encode()).hexdigest(),
            "quote": quote,
            "locator": f"Costs screen, entered by {by}",
        },
    }
    for change in changes:
        target = next(
            (c for c in components if c["type"] == change["type"] and c["side"] == change["side"]),
            None,
        )
        if target is None:
            raise ScheduleError(f"no such component: {change['type']} {change['side']}")
        for field in ("rate_pct", "amount", "minimum", "maximum"):
            if field in change:
                target[field] = None if change[field] is None else str(change[field])
        target["source"] = "owner_entered"
    new = {
        **doc, "id": f"{src.broker}-{src.product.lower()}-{valid_from}", "version": f"{now.date()}.1", "valid_from": str(valid_from),
        "valid_until": None if valid_until is None else str(valid_until), "status": "extracted_unverified", "verified_by": None, "verified_at": None,
        "notes": f"New version entered by {by} on {now.date()}: {quote}", "components": components, "sources": sources,
    }  # fmt: skip
    with conn.transaction():
        open_ended = conn.execute(
            "SELECT schedule_id, version, doc FROM cost_schedule WHERE broker=%s AND product=%s AND valid_until IS NULL AND valid_from < %s FOR UPDATE",
            (src.broker, src.product, valid_from),
        ).fetchone()
        if open_ended is not None:
            closed = {**open_ended[2], "valid_until": str(valid_from - timedelta(days=1))}
            conn.execute(
                "UPDATE cost_schedule SET valid_until=%s, doc=%s, doc_hash=%s WHERE schedule_id=%s AND version=%s",
                (
                    valid_from - timedelta(days=1),
                    Jsonb(closed),
                    schedule_from_dict(closed).doc_hash,
                    open_ended[0],
                    open_ended[1],
                ),
            )
        return add(conn, new, actor=actor, now=now)


def add_provider(
    conn: psycopg.Connection,
    name: str,
    *,
    template_broker: str,
    valid_from: date,
    note: str,
    by: str,
    actor: UUID | None,
    now: datetime,
) -> list[Schedule]:
    """A new provider (broker): start from a copy of another provider's schedules in force, so the structure of the charges is
    there to edit. Nothing cites the template's documents: every component's source is the person's note (provenance
    "owner-entered"), and the schedules are unverified until a person enters the real rates and verifies them."""
    broker = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not broker:
        raise ScheduleError("a provider needs a name made of letters or digits")
    if (
        conn.execute("SELECT 1 FROM cost_schedule WHERE broker=%s", (broker,)).fetchone()
        is not None
    ):
        raise ScheduleError(f"the provider {broker} already exists")
    templates = conn.execute(
        "SELECT doc FROM cost_schedule WHERE broker=%s AND valid_until IS NULL ORDER BY product",
        (template_broker,),
    ).fetchall()
    if not templates:
        raise ScheduleError(f"{template_broker} has no schedule in force to copy")
    quote = (
        note.strip()
        or f"copied from {template_broker} by {by}; the real rates are still to be entered"
    )
    sources = {
        "owner_entered": {
            "url": "owner-entered",
            "retrieved_at": now.isoformat(),
            "sha256": hashlib.sha256(quote.encode()).hexdigest(),
            "quote": quote,
            "locator": f"Costs screen, entered by {by}",
        }
    }
    made = []
    with conn.transaction():
        for (doc,) in templates:
            new = {
                **doc, "id": f"{broker}-{doc['product'].lower()}-{valid_from}", "version": f"{now.date()}.1", "broker": broker,
                "name": f"{name.strip()} {doc['product'].lower()}", "valid_from": str(valid_from), "valid_until": None,
                "status": "extracted_unverified", "verified_by": None, "verified_at": None,
                "notes": f"Provider added by {by} on {now.date()} as a copy of {template_broker}: {quote}",
                "sources": sources, "components": [{**c, "source": "owner_entered"} for c in doc["components"]],
            }  # fmt: skip
            made.append(add(conn, new, actor=actor, now=now))
    return made


def remove(conn: psycopg.Connection, schedule_id: str, version: str) -> None:
    row = conn.execute(
        "SELECT status FROM cost_schedule WHERE schedule_id=%s AND version=%s FOR UPDATE",
        (schedule_id, version),
    ).fetchone()
    if row is None:
        raise ScheduleError(f"no such schedule: {schedule_id} {version}")
    if row[0] == "verified":
        raise ScheduleError("a verified schedule cannot be removed")
    conn.execute(
        "DELETE FROM cost_schedule WHERE schedule_id=%s AND version=%s", (schedule_id, version)
    )


def load_book(
    conn: psycopg.Connection, broker: str, allowed_statuses: Iterable[str] = ("verified",)
) -> ScheduleBook:
    rows = conn.execute("SELECT doc FROM cost_schedule WHERE broker=%s", (broker,)).fetchall()
    return ScheduleBook((schedule_from_dict(r[0]) for r in rows), allowed_statuses=allowed_statuses)

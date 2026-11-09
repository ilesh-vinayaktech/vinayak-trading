# ruff: noqa: E501  (SQL statements are kept on one line each for review)
"""Read the explicit security-conversion instructions the ledger consumes. Only VERIFIED rows are
returned as `Conversion`s; a provisional or rejected row, and any bare SAME_ISSUER_ISIN_CHANGE
relationship, converts nothing: a held position is then flagged as unmodelled instead."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.ledger.ledger import Conversion


def conversion_ref(source: int, target: int, effective: date) -> str:
    return f"convert:{source}:{target}:{effective}"


def load_conversions(conn: psycopg.Connection) -> list[Conversion]:
    """VERIFIED instructions, oldest first (none before migration 025)."""
    table = conn.execute("SELECT to_regclass('security_conversion')").fetchone()
    if table is None or table[0] is None:
        return []
    rows = conn.execute(
        "SELECT source_instrument_id, target_instrument_id, effective_date, ratio_num, ratio_den,"
        " last_source_session, absorbs_ex_date, absorbs_kind, evidence FROM security_conversion"
        " WHERE verification_status='VERIFIED' ORDER BY effective_date, conversion_id"
    ).fetchall()
    return [
        Conversion(
            source=src, target=tgt, effective=eff, num=num, den=den,
            ref=conversion_ref(src, tgt, eff), verified=True, evidence=tuple(evidence),
            last_source_session=last,
            absorbs=(ex, kind) if ex is not None and kind is not None else None,
        )
        for src, tgt, eff, num, den, last, ex, kind, evidence in rows
    ]  # fmt: skip


class ConversionRecordError(Exception):
    pass


def store_conversion(conn: psycopg.Connection, doc: Mapping[str, Any], now: datetime) -> int:
    """Record one reviewed instruction from its config (ISINs, not ids, so it is portable between
    databases). Returns 1 if inserted, 0 if already recorded. A VERIFIED instruction must cite evidence;
    both instruments must already exist in the master."""
    status = doc["verification_status"]
    if status == "VERIFIED" and not doc["evidence"]:
        raise ConversionRecordError("a VERIFIED conversion must cite evidence")
    ids = {}
    for role in ("source", "target"):
        row = conn.execute(
            "SELECT instrument_id FROM instrument WHERE isin=%s", (doc[f"{role}_isin"],)
        ).fetchone()
        if row is None:
            raise ConversionRecordError(f"no instrument with {role} ISIN {doc[f'{role}_isin']}")
        ids[role] = row[0]
    effective = date.fromisoformat(doc["effective_date"])
    rel = conn.execute(
        "SELECT relationship_id FROM corporate_action_relationship WHERE relationship_type="
        "'SAME_ISSUER_ISIN_CHANGE' AND source_instrument_id=%s AND target_instrument_id=%s AND effective_date=%s",
        (ids["source"], ids["target"], effective),
    ).fetchone()
    absorbs = doc.get("absorbs") or {}
    last = doc.get("last_source_session")
    cur = conn.execute(
        "INSERT INTO security_conversion (source_instrument_id, target_instrument_id, effective_date,"
        " last_source_session, ratio_num, ratio_den, relationship_id, absorbs_ex_date, absorbs_kind,"
        " evidence, verification_status, review_decision_id, recorded_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (ids["source"], ids["target"], effective, date.fromisoformat(last) if last else None,
         doc["ratio_num"], doc["ratio_den"], rel[0] if rel else None,
         date.fromisoformat(absorbs["ex_date"]) if absorbs else None, absorbs.get("kind"),
         Jsonb(doc["evidence"]), status, doc.get("review_decision_id"), now),
    )  # fmt: skip
    return cur.rowcount

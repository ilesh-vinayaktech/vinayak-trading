"""Hand/OCR transcriptions of releases the parser cannot read (scanned images). A transcription is
a version-controlled data file with its method, the source document's sha256 and how it was checked;
it is loaded as PROVISIONAL evidence rows for the CURRENT parser version, so it survives parser
upgrades. It is never trusted blindly: the source hash must match the stored original."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.data.index_releases import map_symbol
from algo.data.providers.nse_index_releases import PARSER_VERSION, canon

REQUIRED = ("doc_id", "announced", "source_sha256", "method", "verification", "rows")
CLASSES = ("PARSED", "NOT_RELEVANT")


class TranscriptionError(Exception):
    pass


def store_transcription(
    conn: psycopg.Connection, doc: Mapping[str, Any], *, actual_sha256: str
) -> int:
    """Insert the transcribed rows. Returns rows stored (0 when already loaded)."""
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise TranscriptionError(f"transcription is missing {missing}")
    if not doc["verification"]:
        raise TranscriptionError("a transcription must say how it was checked")
    if doc["source_sha256"] != actual_sha256:
        raise TranscriptionError("the stored original differs from the one that was transcribed")
    label = doc.get("classification", "PARSED")
    if label not in CLASSES:
        raise TranscriptionError(f"classification must be one of {CLASSES}")
    if doc["rows"] and label != "PARSED":
        raise TranscriptionError("a transcription with constituent rows is PARSED")
    if not doc["rows"] and (label == "PARSED" or not doc.get("summary")):
        raise TranscriptionError("a transcription with no rows must be NOT_RELEVANT and say why")
    if doc["rows"] and "effective_from" not in doc:
        raise TranscriptionError("transcribed rows need their effective_from")
    doc_id = doc["doc_id"]
    effective = date.fromisoformat(doc["effective_from"]) if doc["rows"] else date.min
    row = conn.execute(
        "SELECT 1 FROM index_release_document WHERE doc_id=%s AND parser_version=%s",
        (doc_id, PARSER_VERSION),
    ).fetchone()
    if row is None:
        raise TranscriptionError(f"{doc_id} has not been parsed yet: run parse_index_releases.py")
    stored = 0
    with conn.transaction():
        for r in doc["rows"]:
            iid, status = map_symbol(conn, r["symbol"], effective, r["action"])
            cur = conn.execute(
                "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,"
                "component,action,symbol,company,effective_from,raw_text,instrument_id,"
                "mapping_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (doc_id, PARSER_VERSION, r["page"], r["section_no"], r["section"],
                 canon(r["section"]), r["action"], r["symbol"], r["company"], effective,
                 f"OCR: {r['company']} {r['symbol']}", iid, status),
            )  # fmt: skip
            stored += cur.rowcount
        note = {"transcription": doc["method"], "verification": doc["verification"]}
        if doc.get("summary"):
            note["summary"] = doc["summary"]
        reason = f"scanned image, transcribed: {doc['method']}" + (
            f" - {doc['summary']}" if doc.get("summary") else ""
        )
        conn.execute(
            "UPDATE index_release_document SET classification=%s, classification_reason=%s,"
            " notes = notes || %s::jsonb WHERE doc_id=%s AND parser_version=%s"
            " AND NOT (notes @> %s::jsonb)",
            (label, reason, Jsonb([note]), doc_id, PARSER_VERSION, Jsonb([note])),
        )
    return stored

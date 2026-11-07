"""Persist parsed press releases as PROVISIONAL evidence and report what is unresolved."""

from __future__ import annotations

from datetime import date, datetime

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.providers.nse_index_releases import PARSER_VERSION, Release

SOURCE = "nse"


def _map(conn: psycopg.Connection, symbol: str, on: date) -> tuple[int | None, str]:
    row = conn.execute(
        "SELECT instrument_id FROM instrument_alias WHERE source=%s AND source_symbol=%s"
        " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)",
        (SOURCE, symbol, on, on),
    ).fetchone()
    if row:
        return int(row[0]), "MAPPED"
    # a dummy symbol is a zero-price placeholder for a demerged entity, never a tradable instrument
    return None, "PLACEHOLDER_SECURITY" if symbol.startswith("DUMMY") else "UNMAPPED_SYMBOL"


def store_release(
    conn: psycopg.Connection, doc_id: str, release: Release, *, source_url: str, source_hash: str,
    now: datetime,
) -> int:  # fmt: skip
    """Store one parsed release (idempotent per doc + parser version). Returns rows stored."""
    with conn.transaction():
        cur = conn.execute(
            "INSERT INTO index_release_document (doc_id,parser_version,announced,source_url,"
            "source_hash,kind,sections,notes,parsed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT DO NOTHING",
            (doc_id, PARSER_VERSION, release.announced, source_url, source_hash, release.kind,
             Jsonb(list(release.sections)), Jsonb(list(release.notes)), require_utc(now)),
        )  # fmt: skip
        if cur.rowcount == 0:
            return 0
        for r in release.rows:
            iid, status = _map(conn, r.symbol, r.effective_from or release.announced)
            conn.execute(
                "INSERT INTO index_release_row (doc_id,parser_version,page,section_no,section_name,"
                "component,action,symbol,company,effective_from,related_symbol,raw_text,"
                "instrument_id,mapping_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (doc_id, PARSER_VERSION, r.page, r.section_no, r.section_name, r.component,
                 r.action, r.symbol, r.company, r.effective_from, r.related_symbol, r.raw_text,
                 iid, status),
            )  # fmt: skip
    return len(release.rows)


def unresolved(conn: psycopg.Connection) -> dict[str, list[tuple[str, ...]]]:
    """What a person must look at: documents we could not place, and component rows whose symbol
    is not (yet) a known instrument."""
    manual = conn.execute(
        "SELECT doc_id, announced::text FROM index_release_document WHERE kind='MANUAL_REVIEW'"
        " AND parser_version=%s ORDER BY announced",
        (PARSER_VERSION,),
    ).fetchall()
    rows = conn.execute(
        "SELECT mapping_status, symbol, doc_id, effective_from::text FROM index_release_row"
        " WHERE component IS NOT NULL AND mapping_status <> 'MAPPED' AND parser_version=%s"
        " ORDER BY effective_from, symbol",
        (PARSER_VERSION,),
    ).fetchall()
    return {
        "manual_documents": [tuple(r) for r in manual],
        "unmapped_rows": [tuple(r) for r in rows],
    }


def remap(conn: psycopg.Connection) -> int:
    """Re-resolve rows still UNMAPPED after instruments/aliases were added. Returns rows fixed."""
    on = "COALESCE(r.effective_from, DATE '9999-12-31')"
    return conn.execute(
        "UPDATE index_release_row r SET instrument_id=a.instrument_id, mapping_status='MAPPED'"
        " FROM instrument_alias a WHERE r.mapping_status='UNMAPPED_SYMBOL' AND a.source=%s"
        f" AND a.source_symbol=r.symbol AND a.valid_from <= {on}"
        f" AND (a.valid_to IS NULL OR {on} < a.valid_to)",
        (SOURCE,),
    ).rowcount

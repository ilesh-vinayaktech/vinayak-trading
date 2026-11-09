"""Reviewed placeholder replacements: the listing of a demerged entity took over the membership of
its zero-price DUMMY placeholder on its listing date. Checked against the stored releases (the
exclusion row must name both symbols; the placeholder must have been included before the listing
and the exclusion must come after it). The two entities are never merged and no identity or
alias table is touched."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.data.providers.nse_index_releases import PARSER_VERSION

REQUIRED = ("evidence_doc", "announced", "source_sha256", "method", "verification", "replacements")


class ReplacementError(Exception):
    pass


def store_replacements(
    conn: psycopg.Connection, doc: Mapping[str, Any], *, actual_sha256: str, now: datetime
) -> int:
    """Insert the replacements of one exclusion release. Returns rows stored (0 if loaded)."""
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise ReplacementError(f"replacements are missing {missing}")
    if not doc["verification"]:
        raise ReplacementError("a replacement file must say how it was checked")
    if doc["source_sha256"] != actual_sha256:
        raise ReplacementError("the stored original differs from the one that was transcribed")
    prepared = []
    for r in doc["replacements"]:
        listed_on = date.fromisoformat(r["listed_on"])
        excluded = (
            conn.execute(
                "SELECT min(effective_from) FROM index_release_row"
                " WHERE doc_id=%s AND parser_version=%s AND action='EXCLUDED' AND symbol=%s"
                " AND (related_symbol=%s OR (related_symbol IS NULL AND symbol=%s))"
                " AND component IS NOT NULL",
                (
                    doc["evidence_doc"],
                    PARSER_VERSION,
                    r["symbol"],
                    r["placeholder"],
                    r["placeholder"],
                ),
            ).fetchone()
            or (None,)
        )[0]
        if excluded is None:
            raise ReplacementError(
                f"{doc['evidence_doc']} has no exclusion of {r['symbol']} naming {r['placeholder']}"
            )
        included = (
            conn.execute(
                "SELECT min(effective_from) FROM index_release_row WHERE parser_version=%s"
                " AND action='INCLUDED' AND symbol=%s AND component IS NOT NULL",
                (PARSER_VERSION, r["placeholder"]),
            ).fetchone()
            or (None,)
        )[0]
        if included is None or not included < listed_on < excluded:
            raise ReplacementError(
                f"{r['symbol']} listed {listed_on}: not between the placeholder's inclusion"
                f" ({included}) and the exclusion ({excluded})"
            )
        prepared.append(r)
    stored = 0
    with conn.transaction():
        for r in prepared:
            cur = conn.execute(
                "INSERT INTO index_placeholder_replacement (evidence_doc,placeholder,symbol,"
                "listed_on,quote,method,verification,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (doc["evidence_doc"], r["placeholder"], r["symbol"], r["listed_on"], r["quote"],
                 doc["method"], Jsonb(doc["verification"]), now),
            )  # fmt: skip
            stored += cur.rowcount
    return stored

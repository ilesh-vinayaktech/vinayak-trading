"""Row-level revocations: a later release says one announced change (one stock, one index) was
revoked. The announcement and the revocation stay separate evidence; this module links them after
checking the source hash and that the revoked change was really announced. It never edits
index_release_row and never creates a compensating membership transition."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.data.providers.nse_index_releases import PARSER_VERSION, canon

REQUIRED = ("authority_doc", "announced", "source_sha256", "method", "verification", "revocations")
KINDS = {"INCLUSION_REVOKED": "INCLUDED", "EXCLUSION_REVOKED": "EXCLUDED"}


class RevocationError(Exception):
    pass


def store_revocations(
    conn: psycopg.Connection, doc: Mapping[str, Any], *, actual_sha256: str, now: datetime
) -> int:
    """Insert the revocations of one release. Returns rows stored (0 when already loaded)."""
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise RevocationError(f"revocations are missing {missing}")
    if not doc["verification"]:
        raise RevocationError("a revocation file must say how it was checked")
    if doc["source_sha256"] != actual_sha256:
        raise RevocationError("the stored original differs from the one that was transcribed")
    authority_date = date.fromisoformat(doc["announced"])
    prepared = []
    for r in doc["revocations"]:
        if r["kind"] not in KINDS:
            raise RevocationError(f"kind must be one of {sorted(KINDS)}")
        component = canon(r["section"])
        if component is None:
            raise RevocationError(f"{r['section']!r} is not a Nifty 200 component index")
        effective = date.fromisoformat(r["effective_from"])
        action = KINDS[r["kind"]]
        original = conn.execute(
            "SELECT d.announced FROM index_release_row r JOIN index_release_document d"
            " USING (doc_id, parser_version) WHERE r.doc_id=%s AND r.parser_version=%s"
            " AND r.component=%s AND r.symbol=%s AND r.action=%s AND r.effective_from=%s LIMIT 1",
            (r["revokes_doc_id"], PARSER_VERSION, component, r["symbol"], action, effective),
        ).fetchone()
        if original is None:
            raise RevocationError(
                f"no announced {action} row for {r['symbol']} in {component} on {effective}"
                f" in {r['revokes_doc_id']}"
            )
        if authority_date < original[0]:
            raise RevocationError("a release cannot revoke a change before it was announced")
        if authority_date >= effective:
            raise RevocationError("a revocation published after the change took effect")
        prepared.append((r, component, effective))
    stored = 0
    with conn.transaction():
        for r, component, effective in prepared:
            cur = conn.execute(
                "INSERT INTO index_release_revocation (doc_id,component,symbol,kind,effective_from,"
                "authority_doc,authority_date,authority_quote,method,verification,recorded_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (r["revokes_doc_id"], component, r["symbol"], r["kind"], effective,
                 doc["authority_doc"], authority_date, r["quote"], doc["method"],
                 Jsonb(doc["verification"]), now),
            )  # fmt: skip
            stored += cur.rowcount
    return stored

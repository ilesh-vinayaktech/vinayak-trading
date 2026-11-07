"""Glue between the parsed releases / snapshot in the database and the pure derivation."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import psycopg

from algo.data.providers.nse_index_releases import PARSER_VERSION
from algo.data.universe import add_event
from algo.data.universe_derive import BOUNDARY, M2, CEvent, Derived, Report, build_report

SNAPSHOT_INDEX = "NIFTY200"
BACKWARD = "derived:backward-from-current-snapshot"
FAILING = {"NON_ALTERNATING", "SNAPSHOT_MISMATCH", "CHECKPOINT_MISSING", "CHECKPOINT_EXTRA"}


def load_inputs(
    conn: psycopg.Connection,
) -> tuple[list[CEvent], set[int], list[str], date, list[tuple[str, str, str, str]]]:
    """(component events, current official Nifty 200 ids, manual-review documents, snapshot date,
    undated rows). Undated rows cannot be placed in time; they are returned, never dropped."""
    rows = conn.execute(
        "SELECT r.instrument_id, r.symbol, r.component, r.action, r.effective_from, d.announced,"
        " r.doc_id, r.page, r.mapping_status FROM index_release_row r"
        " JOIN index_release_document d USING (doc_id, parser_version)"
        " WHERE r.component IS NOT NULL AND r.review_status <> 'REJECTED' AND r.parser_version=%s"
        " AND r.effective_from IS NOT NULL ORDER BY r.effective_from, r.row_id",
        (PARSER_VERSION,),
    ).fetchall()
    undated = [
        (r[0], r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT symbol, component, action, doc_id FROM index_release_row"
            " WHERE component IS NOT NULL AND review_status <> 'REJECTED'"
            " AND parser_version=%s AND effective_from IS NULL",
            (PARSER_VERSION,),
        )
    ]
    events = [
        CEvent(f"i:{iid}" if iid else f"s:{sym}", sym, comp, act, eff, ann, doc, page,
               placeholder=status == "PLACEHOLDER_SECURITY")
        for iid, sym, comp, act, eff, ann, doc, page, status in rows
    ]  # fmt: skip
    snap = conn.execute(
        "SELECT as_of FROM index_snapshot WHERE index_id=%s ORDER BY as_of DESC LIMIT 1",
        (SNAPSHOT_INDEX,),
    ).fetchone()
    if snap is None:
        raise ValueError("no current Nifty 200 snapshot loaded")
    ids = {
        r[0]
        for r in conn.execute(
            "SELECT instrument_id FROM index_snapshot WHERE index_id=%s AND as_of=%s",
            (SNAPSHOT_INDEX, snap[0]),
        )
    }
    manual = [
        r[0]
        for r in conn.execute(
            "SELECT doc_id FROM index_release_document WHERE kind='MANUAL_REVIEW'"
            " AND parser_version=%s AND announced >= %s ORDER BY announced",
            (PARSER_VERSION, date(2017, 1, 1)),
        )
    ]
    return events, ids, manual, snap[0], undated


def derive(conn: psycopg.Connection) -> tuple[Report, set[int], date]:
    events, ids, manual, as_of, undated = load_inputs(conn)
    return build_report(events, ids, manual, undated), ids, as_of


def persist(conn: psycopg.Connection, report: Report, snapshot: set[int], now: datetime) -> int:
    """Store the current-methodology series as PROVISIONAL membership events, for instruments whose
    own history reconciles (no alternation / snapshot / checkpoint discrepancy). Also writes the
    initial state (members just before the first event, rebuilt backwards from the snapshot).
    NO coverage is declared: that stays a human decision. Returns events written."""
    bad = {d.key for d in report.discrepancies if d.kind in FAILING}
    events = [
        d for d in report.derived
        if d.index_id == M2 and d.key.startswith("i:") and d.key not in bad and not d.placeholder
    ]  # fmt: skip
    state = set(snapshot)
    for d in sorted(events, key=lambda x: (x.effective, x.key), reverse=True):
        (state.discard if d.event_type == "ADD" else state.add)(int(d.key[2:]))
    sym: dict[int, str] = dict(
        conn.execute("SELECT instrument_id, symbol FROM instrument").fetchall()
    )
    stamp = hashlib.sha256(",".join(map(str, sorted(snapshot))).encode()).hexdigest()
    initial = BOUNDARY - timedelta(days=1)
    n = 0
    for iid in sorted(state):
        add_event(conn, index_id=M2, instrument_id=iid, symbol=sym[iid], event_type="ADD",
                  announcement_date=initial, effective_from=initial, now=now,
                  source_url=BACKWARD, source_hash=stamp)  # fmt: skip
        n += 1
    meta = conn.execute("SELECT doc_id, source_url, source_hash FROM index_release_document")
    docs: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for doc_id, url, digest in meta.fetchall():
        docs[doc_id], hashes[doc_id] = url, digest
    for d in events:
        _write(conn, d, docs, hashes, now)
        n += 1
    return n


def _write(conn: psycopg.Connection, d: Derived, urls: dict[str, str], hashes: dict[str, str],
           now: datetime) -> None:  # fmt: skip
    doc = d.docs[0]
    add_event(conn, index_id=d.index_id, instrument_id=int(d.key[2:]), symbol=d.symbol,
              event_type=d.event_type, announcement_date=d.announced, effective_from=d.effective,
              source_url=urls[doc], source_hash=hashes[doc], now=now)  # fmt: skip

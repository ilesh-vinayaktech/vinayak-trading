# ruff: noqa: E501
"""Load a reconstructed membership (membership_intervals.csv + membership_events.csv) as stored, PROVISIONAL membership events and a
PROVISIONAL coverage declaration. Only intervals of real instruments are loaded: placeholders and unmapped symbols have no instrument to
point at (they stay listed in the reconstruction's exceptions). Loading never verifies anything: VERIFIED is the owner's act."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import psycopg

from algo.data.universe import UniverseError, add_event, declare_coverage

BASELINE = "reconstruction:no-release-event"  # the interval begins at the window start or by an identity handover, not by a release


@dataclass(frozen=True)
class Loaded:
    added: int
    existing: int
    coverage_id: int
    clamped: int = 0  # events whose release came after their effective date: stored as effective on the day announced (no lookahead)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _urls(conn: psycopg.Connection) -> dict[str, str]:
    """doc_id -> source url (the same for every parser version of a document)."""
    return {
        d: u
        for d, u in conn.execute(
            "SELECT DISTINCT doc_id, source_url FROM index_release_document"
        ).fetchall()
    }


def _wanted(
    intervals: list[dict[str, str]],
    events: list[dict[str, str]],
    urls: dict[str, str],
    baseline_hash: str,
) -> list[tuple[int, str, str, date, date, str, str]]:
    """Events are matched to interval boundaries by symbol, type and date, not entity: after an ISIN change the release event names the current
    instrument while the interval belongs to the one that was listed then. (instrument_id, symbol, ADD|REMOVE, announced, effective, url, hash) for every boundary of a tradable instrument interval."""
    by_key = {
        (e["symbol"], e["event_type"], date.fromisoformat(e["effective_from"])): e
        for e in events
        if e["tradable"] == "True"
    }
    used: set[tuple[str, str, date]] = set()
    out = []
    for iv in intervals:
        if iv["kind"] != "INSTRUMENT" or iv["tradable"] != "True":
            continue
        iid = int(iv["instrument_id"])
        bounds = [("ADD", date.fromisoformat(iv["start"]))]
        if iv["end_exclusive"]:
            bounds.append(("REMOVE", date.fromisoformat(iv["end_exclusive"])))
        for kind, eff in bounds:
            key = (iv["symbol"], kind, eff)
            e = by_key.get(key)
            if e is None:
                out.append(
                    (
                        iid,
                        iv["symbol"],
                        kind,
                        eff,
                        eff,
                        f"{BASELINE}:{iv['start_basis']}",
                        baseline_hash,
                    )
                )
                continue
            used.add(key)
            doc = e["source_docs"]
            if doc not in urls:
                raise UniverseError(
                    f"event {key} cites document {doc!r}, which is not in index_release_document"
                )
            out.append(
                (
                    iid,
                    iv["symbol"],
                    kind,
                    date.fromisoformat(e["announcement_date"]),
                    eff,
                    urls[doc],
                    e["source_hashes"],
                )
            )
    stray = sorted(set(by_key) - used, key=str)
    if stray:
        raise UniverseError(
            f"{len(stray)} tradable events match no interval boundary, e.g. {stray[0]}: the files disagree"
        )
    return out


def load_reconstruction(
    conn: psycopg.Connection,
    *,
    directory: Path,
    index_id: str,
    covered_from: date,
    covered_until: date,
    basis: str,
    now: datetime,
) -> Loaded:
    """Idempotent: an event already stored (same index, instrument, type, effective date) is left as it is."""
    intervals = _read(directory / "membership_intervals.csv")
    events = _read(directory / "membership_events.csv")
    baseline_hash = hashlib.sha256(
        (directory / "membership_intervals.csv").read_bytes()
    ).hexdigest()
    added = existing = clamped = 0
    for iid, sym, kind, announced, eff, url, digest in _wanted(
        intervals, events, _urls(conn), baseline_hash
    ):
        if (
            eff < announced
        ):  # retrospective handover (D5): the table cannot say "effective before announced", and knowing it earlier would be lookahead
            eff, clamped = announced, clamped + 1
        row = conn.execute(
            "SELECT 1 FROM index_membership_event WHERE index_id=%s AND instrument_id=%s AND event_type=%s AND effective_from=%s",
            (index_id, iid, kind, eff),
        ).fetchone()
        if row:
            existing += 1
            continue
        add_event(conn, index_id=index_id, instrument_id=iid, symbol=sym, event_type=kind, announcement_date=announced,
                  effective_from=eff, source_url=url, source_hash=digest, now=now)  # fmt: skip
        added += 1
    have = conn.execute(
        "SELECT coverage_id FROM index_membership_coverage WHERE index_id=%s AND covered_from=%s AND covered_until=%s",
        (index_id, covered_from, covered_until),
    ).fetchone()
    cid = (
        int(have[0])
        if have
        else declare_coverage(conn, index_id, covered_from, covered_until, basis, now)
    )
    return Loaded(added, existing, cid, clamped)

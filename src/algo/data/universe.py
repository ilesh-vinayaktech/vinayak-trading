"""Point-in-time index membership. Events (ADD / REMOVE) carry an announcement date and an
effective date; membership on a day is derived from them, never from a current snapshot.

Rules enforced here:
  * a day outside declared coverage is UNKNOWN: UniverseGap, never today's list (strict mode needs
    VERIFIED coverage and VERIFIED events; research mode accepts PROVISIONAL, never REJECTED)
  * a decision made on `known_on` cannot see changes announced after it
  * an ADD while already a member, or a REMOVE while not one, is an inconsistency, not guessed away
Index membership is what NSE says; whether a strategy may TRADE a member is a separate question."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from algo.core.clock import require_utc

STATUSES = ("VERIFIED", "PROVISIONAL", "REJECTED")


class UniverseError(Exception):
    pass


class UniverseGap(UniverseError):
    """Membership on that day is not established."""


class UniverseInconsistent(UniverseError):
    pass


@dataclass(frozen=True)
class Interval:
    instrument_id: int
    start: date  # first day a member
    end: date | None  # first day NOT a member (exclusive); None = still a member


def add_event(
    conn: psycopg.Connection, *, index_id: str, instrument_id: int, symbol: str, event_type: str,
    announcement_date: date, effective_from: date, source_url: str, source_hash: str, now: datetime,
) -> int:  # fmt: skip
    if event_type not in ("ADD", "REMOVE"):
        raise UniverseError("event_type must be ADD or REMOVE")
    if effective_from < announcement_date:
        raise UniverseError("a change cannot take effect before it is announced")
    if not source_url or not source_hash:
        raise UniverseError("every event needs its source url and document hash")
    row = conn.execute(
        "INSERT INTO index_membership_event (index_id,instrument_id,symbol_at_event,event_type,"
        "announcement_date,effective_from,source_url,source_hash,ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id",
        (index_id, instrument_id, symbol, event_type, announcement_date, effective_from,
         source_url, source_hash, require_utc(now)),
    ).fetchone()  # fmt: skip
    assert row is not None
    return int(row[0])


def set_event_status(
    conn: psycopg.Connection, event_id: int, status: str, *, by: str, now: datetime
) -> None:
    if status not in STATUSES:
        raise UniverseError(f"status must be one of {STATUSES}")
    if not by:
        raise UniverseError("a reviewer name is required")
    cur = conn.execute(
        "UPDATE index_membership_event SET verified_status=%s, verified_by=%s, verified_at=%s"
        " WHERE event_id=%s",
        (status, by, require_utc(now), event_id),
    )
    if cur.rowcount != 1:
        raise UniverseError(f"no event {event_id}")


def declare_coverage(
    conn: psycopg.Connection, index_id: str, covered_from: date, covered_until: date | None,
    basis: str, now: datetime,
) -> int:  # fmt: skip
    if not basis.strip():
        raise UniverseError("say how completeness was established")
    row = conn.execute(
        "INSERT INTO index_membership_coverage (index_id,covered_from,covered_until,basis,"
        "declared_at) VALUES (%s,%s,%s,%s,%s) RETURNING coverage_id",
        (index_id, covered_from, covered_until, basis, require_utc(now)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def verify_coverage(conn: psycopg.Connection, coverage_id: int, *, by: str, now: datetime) -> None:
    if not by:
        raise UniverseError("a reviewer name is required")
    cur = conn.execute(
        "UPDATE index_membership_coverage SET verified_status='VERIFIED', verified_by=%s,"
        " verified_at=%s WHERE coverage_id=%s",
        (by, require_utc(now), coverage_id),
    )
    if cur.rowcount != 1:
        raise UniverseError(f"no coverage {coverage_id}")


def _allowed(strict: bool) -> tuple[str, ...]:
    return ("VERIFIED",) if strict else ("VERIFIED", "PROVISIONAL")


def covered(conn: psycopg.Connection, index_id: str, day: date, *, strict: bool = True) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM index_membership_coverage WHERE index_id=%s"
        " AND verified_status = ANY(%s) AND covered_from <= %s"
        " AND (covered_until IS NULL OR covered_until >= %s))",
        (index_id, list(_allowed(strict)), day, day),
    ).fetchone()
    assert row is not None
    return bool(row[0])


def _events(
    conn: psycopg.Connection, index_id: str, strict: bool, known_on: date | None, upto: date | None
) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT instrument_id, event_type, effective_from FROM index_membership_event"
        " WHERE index_id=%s AND verified_status = ANY(%s)"
        " AND (%s::date IS NULL OR announcement_date <= %s)"
        " AND (%s::date IS NULL OR effective_from <= %s)"
        " ORDER BY instrument_id, effective_from, event_type",
        (index_id, list(_allowed(strict)), known_on, known_on, upto, upto),
    ).fetchall()


def _walk(events: list[tuple[Any, ...]]) -> list[Interval]:
    out: list[Interval] = []
    open_: dict[int, date] = {}
    for iid, kind, eff in events:
        if kind == "ADD":
            if iid in open_:
                raise UniverseInconsistent(
                    f"instrument {iid} ADDed on {eff} while already a member"
                )
            open_[iid] = eff
        else:
            if iid not in open_:
                raise UniverseInconsistent(f"instrument {iid} REMOVEd on {eff} but not a member")
            out.append(Interval(iid, open_.pop(iid), eff))
    out.extend(Interval(i, s, None) for i, s in open_.items())
    return sorted(out, key=lambda x: (x.instrument_id, x.start))


def intervals(conn: psycopg.Connection, index_id: str, *, strict: bool = True) -> list[Interval]:
    """Membership intervals derived from the (verified) events."""
    return _walk(_events(conn, index_id, strict, None, None))


def members_on(
    conn: psycopg.Connection, index_id: str, day: date, *, known_on: date | None = None,
    strict: bool = True,
) -> set[int]:  # fmt: skip
    """Instruments in the index on `day`, as known on `known_on` (default: `day` itself).
    Changes announced after `known_on` are invisible, so a future reconstitution cannot leak."""
    if not covered(conn, index_id, day, strict=strict):
        mode = "verified" if strict else "declared"
        raise UniverseGap(f"{index_id} membership on {day} is not covered by {mode} history")
    known = known_on or day
    ivs = _walk(_events(conn, index_id, strict, known, day))
    return {i.instrument_id for i in ivs if i.start <= day and (i.end is None or day < i.end)}


def coverage_report(conn: psycopg.Connection, index_id: str) -> dict[str, Any]:
    """What is and is not established, stated explicitly."""
    cov = conn.execute(
        "SELECT covered_from, covered_until, verified_status, basis FROM index_membership_coverage"
        " WHERE index_id=%s ORDER BY covered_from",
        (index_id,),
    ).fetchall()
    counts: dict[str, int] = dict(
        conn.execute(
            "SELECT verified_status, count(*) FROM index_membership_event WHERE index_id=%s"
            " GROUP BY verified_status",
            (index_id,),
        ).fetchall()
    )
    problem = None
    try:
        intervals(conn, index_id, strict=False)
    except UniverseInconsistent as e:
        problem = str(e)
    return {
        "coverage": [
            {"from": str(a), "until": str(b) if b else None, "status": s, "basis": basis}
            for a, b, s, basis in cov
        ],
        "events": {s: int(counts.get(s, 0)) for s in STATUSES},
        "inconsistency": problem,
        "strict_ready": any(c[2] == "VERIFIED" for c in cov)
        and counts.get("PROVISIONAL", 0) == 0
        and problem is None,
    }

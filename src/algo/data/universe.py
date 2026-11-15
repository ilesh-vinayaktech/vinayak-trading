# ruff: noqa: E501
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
    conn: psycopg.Connection, *, index_id: str, instrument_id: int | None, symbol: str, event_type: str,
    announcement_date: date, effective_from: date, source_url: str, source_hash: str, now: datetime,
    constituent_key: str | None = None,
) -> int:  # fmt: skip
    """effective_from is when the change really applied, announcement_date when it could have been known (it may be later: a
    retrospective handover), `now` when we recorded it. A constituent with no tradable instrument (an index placeholder, a symbol not yet
    an instrument) is a member too: pass instrument_id=None and its constituent_key ('p:SYMBOL' or 's:SYMBOL')."""
    if event_type not in ("ADD", "REMOVE"):
        raise UniverseError("event_type must be ADD or REMOVE")
    if instrument_id is None and not constituent_key:
        raise UniverseError("an event needs an instrument or a constituent key")
    if not source_url or not source_hash:
        raise UniverseError("every event needs its source url and document hash")
    key = f"i:{instrument_id}" if instrument_id is not None else constituent_key
    row = conn.execute(
        "INSERT INTO index_membership_event (index_id,instrument_id,constituent_key,symbol_at_event,event_type,"
        "announcement_date,effective_from,source_url,source_hash,ingested_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING event_id",
        (index_id, instrument_id, key, symbol, event_type, announcement_date, effective_from,
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
    conn: psycopg.Connection,
    index_id: str,
    strict: bool,
    known_on: date | None,
    upto: date | None,
    instruments_only: bool = True,
) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT constituent_key, event_type, effective_from FROM index_membership_event"
        " WHERE index_id=%s AND verified_status = ANY(%s)"
        " AND (%s::date IS NULL OR announcement_date <= %s)"
        " AND (%s::date IS NULL OR effective_from <= %s)"
        " AND (NOT %s OR instrument_id IS NOT NULL)"
        " ORDER BY constituent_key, effective_from, event_type",
        (index_id, list(_allowed(strict)), known_on, known_on, upto, upto, instruments_only),
    ).fetchall()


def _walk_keys(events: list[tuple[Any, ...]]) -> list[tuple[str, date, date | None]]:
    out: list[tuple[str, date, date | None]] = []
    open_: dict[str, date] = {}
    for key, kind, eff in events:
        if kind == "ADD":
            if key in open_:
                raise UniverseInconsistent(f"{key} ADDed on {eff} while already a member")
            open_[key] = eff
        else:
            if key not in open_:
                raise UniverseInconsistent(f"{key} REMOVEd on {eff} but not a member")
            out.append((key, open_.pop(key), eff))
    out.extend((k, st, None) for k, st in open_.items())
    return out


def _walk(events: list[tuple[Any, ...]]) -> list[Interval]:
    """Intervals of instrument members (every key here is 'i:<id>')."""
    return sorted(
        (Interval(int(k[2:]), st, en) for k, st, en in _walk_keys(events)),
        key=lambda x: (x.instrument_id, x.start),
    )


def intervals(conn: psycopg.Connection, index_id: str, *, strict: bool = True) -> list[Interval]:
    """Membership intervals of instruments, derived from the (verified) events."""
    return _walk(_events(conn, index_id, strict, None, None))


def _known(day: date, known_on: date | None, historical: bool) -> date | None:
    """What a reader may know: by default only what was announced by `day`; `historical` lifts that limit to ask who actually WAS a member."""
    return None if historical else (known_on or day)


def members_on(
    conn: psycopg.Connection, index_id: str, day: date, *, known_on: date | None = None,
    strict: bool = True, historical: bool = False,
) -> set[int]:  # fmt: skip
    """Instruments in the index on `day`, as known on `known_on` (default: `day` itself).
    Changes announced after `known_on` are invisible, so a future reconstitution cannot leak.
    `historical=True` ignores the announcement date and answers who actually was a member (a record, not a decision input)."""
    if not covered(conn, index_id, day, strict=strict):
        mode = "verified" if strict else "declared"
        raise UniverseGap(f"{index_id} membership on {day} is not covered by {mode} history")
    ivs = _walk(_events(conn, index_id, strict, _known(day, known_on, historical), day))
    return {i.instrument_id for i in ivs if i.start <= day and (i.end is None or day < i.end)}


def constituents_on(
    conn: psycopg.Connection, index_id: str, day: date, *, known_on: date | None = None,
    strict: bool = True, historical: bool = False,
) -> set[str]:  # fmt: skip
    """Every constituent key in the index on `day`, tradable or not ('i:<id>', 'p:<SYMBOL>', 's:<SYMBOL>'): the full index, 200 names.
    Being a member, having an instrument, having prices and being eligible to trade are separate questions."""
    if not covered(conn, index_id, day, strict=strict):
        mode = "verified" if strict else "declared"
        raise UniverseGap(f"{index_id} membership on {day} is not covered by {mode} history")
    walked = _walk_keys(
        _events(
            conn, index_id, strict, _known(day, known_on, historical), day, instruments_only=False
        )
    )
    return {k for k, st, en in walked if st <= day and (en is None or day < en)}


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

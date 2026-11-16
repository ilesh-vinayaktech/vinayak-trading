# ruff: noqa: E501
"""Feature definitions, status, materialisations and the one way to read them (docs/vti-phase1-spec.md, item C).

register_all   put the v1 definitions in the database (status DRAFT); a stored (name, version) whose manifest hash differs is refused: that is
               the version guard, an edit to a formula, its module or a helper needs a NEW version
set_status     a status moves only by a new row; a fundamental-family feature can never become USABLE in Phase 1
require_usable a study may name only USABLE features
materialise_month  one feature, one calendar month, one dataset, in one transaction; a rerun of a complete month writes nothing; refuses a month
               that reaches the global holdout
read_features  values for exactly one dataset; a month with no completed run for that dataset raises: it never falls back to another snapshot"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data.reader import PriceReader
from algo.features import registry
from algo.features._shared import SessionBar
from algo.features.fundamental import FilingsHistory
from algo.research import holdout_lock

STATUSES = ("DRAFT", "USABLE", "BLOCKED")
USABLE_FAMILIES = (
    "price",
    "technical",
    "fundamental",
)  # price/volume, the second price set, and the point-in-time fundamental ratios (docs/features.md); anything else is refused
IST = ZoneInfo("Asia/Kolkata")


class FeatureError(Exception):
    pass


def _id(conn: psycopg.Connection, name: str, version: str) -> int:
    row = conn.execute(
        "SELECT feature_id FROM feature_definition WHERE name=%s AND version=%s", (name, version)
    ).fetchone()
    if row is None:
        raise FeatureError(f"feature {name}@{version} is not registered")
    return int(row[0])


def register_all(conn: psycopg.Connection, now: datetime) -> int:
    """Store every definition not yet stored (status DRAFT). A stored definition whose hash differs from the code's is refused for all of them
    before anything is written. Returns how many were new."""
    now = require_utc(now)
    changed = []
    new = []
    for d in registry.DEFINITIONS.values():
        row = conn.execute(
            "SELECT manifest_sha256 FROM feature_definition WHERE name=%s AND version=%s",
            (d.name, d.version),
        ).fetchone()
        if row is None:
            new.append(d)
        elif row[0] != d.manifest_sha256:
            changed.append(f"{d.name}@{d.version}")
    if changed:
        raise FeatureError(
            "these features changed without a new version (their formula, module or a helper differs from what was registered): "
            + ", ".join(changed)
        )
    with conn.transaction():
        for d in new:
            fid = conn.execute(
                "INSERT INTO feature_definition (name, version, manifest, manifest_sha256, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING feature_id",
                (d.name, d.version, Jsonb(dict(d.manifest)), d.manifest_sha256, now),
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'DRAFT','registered; not yet validated','system',%s)",
                (fid, now),
            )
    return len(new)


def status(conn: psycopg.Connection, name: str, version: str) -> str:
    row = conn.execute(
        "SELECT status FROM feature_status WHERE feature_id=%s ORDER BY status_id DESC LIMIT 1",
        (_id(conn, name, version),),
    ).fetchone()
    assert row is not None
    return str(row[0])


def set_status(
    conn: psycopg.Connection,
    name: str,
    version: str,
    new: str,
    *,
    by: str,
    reason: str,
    now: datetime,
) -> None:
    if new not in STATUSES:
        raise FeatureError(f"status must be one of {STATUSES}")
    if not by.strip() or not reason.strip():
        raise FeatureError("a status change needs who and why")
    fid = _id(conn, name, version)
    family = conn.execute(
        "SELECT manifest->>'family' FROM feature_definition WHERE feature_id=%s", (fid,)
    ).fetchone()[0]  # type: ignore[index]
    if new == "USABLE" and family not in USABLE_FAMILIES:
        raise FeatureError(
            f"only {', '.join(USABLE_FAMILIES)} features can be USABLE: family {family!r} is not supported yet"
        )
    conn.execute(
        "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,%s,%s,%s,%s)",
        (fid, new, reason, by, require_utc(now)),
    )


def require_usable(conn: psycopg.Connection, features: list[tuple[str, str]]) -> None:
    """A study may name only USABLE features: anything else is refused, with every offender named."""
    bad = []
    for name, version in features:
        try:
            s = status(conn, name, version)
        except FeatureError:
            bad.append(f"{name}@{version} (not registered)")
            continue
        if s != "USABLE":
            bad.append(f"{name}@{version} ({s})")
    if bad:
        raise FeatureError("these features cannot be named in a study: " + ", ".join(bad))


def bars_from_reader(reader: PriceReader, instrument_id: int, end: date) -> dict[date, SessionBar]:
    """The instrument's sessions up to `end` as feature inputs: adjusted high/low/close, raw close and volume, and when each became visible."""
    loaded = reader.load(instrument_id)
    adj = loaded.history(date(1990, 1, 1), end, adjust="split")
    raw = loaded.history(date(1990, 1, 1), end, adjust="none")
    out: dict[date, SessionBar] = {}
    for a, r in zip(adj.bars, raw.bars, strict=True):
        day = a.ts.astimezone(IST).date()
        out[day] = SessionBar(
            day, a.high, a.low, a.close, r.close, r.volume, a.ts + reader.visible_after
        )
    return out


def _month_end(month: date) -> date:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


Row = tuple[int, date, Decimal, datetime]


def compute_rows(
    name: str,
    month: date,
    bars_by_instrument: Mapping[int, Mapping[date, SessionBar]],
    filings: Mapping[int, FilingsHistory] | None = None,
) -> list[Row]:
    """One feature's rows for one calendar month, in the order they are stored and hashed. Pure: nothing is read or written."""
    end = _month_end(month)
    d = registry.DEFINITIONS[name]
    sessions = [d for d in registry.sessions_from(bars_by_instrument) if d <= end]
    rows: list[Row] = []
    for iid in sorted(bars_by_instrument):
        for day, (value, available_at) in d.calc(
            sessions, bars_by_instrument[iid], (filings or {}).get(iid)
        ).items():
            if month <= day <= end:
                rows.append((iid, day, value, available_at))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def compute_rows_by_month(
    name: str,
    months: Sequence[date],
    bars_by_instrument: Mapping[int, Mapping[date, SessionBar]],
    filings: Mapping[int, FilingsHistory] | None = None,
    heartbeat: Callable[[int, int], None] | None = None,
) -> dict[date, list[Row]]:
    """The rows of one feature for several calendar months in ONE pass over each company, the same rows (and digests) `compute_rows` gives month by month. Computing a month alone
    recomputes the whole history up to it, so doing every month that way costs the square of the number of months; this costs one history. Pure."""
    d = registry.DEFINITIONS[name]
    wanted = set(months)
    end = _month_end(max(wanted))
    sessions = [s for s in registry.sessions_from(bars_by_instrument) if s <= end]
    out: dict[date, list[Row]] = {m: [] for m in sorted(wanted)}
    for k, iid in enumerate(sorted(bars_by_instrument), 1):
        if heartbeat and (k == 1 or k % 200 == 0):
            heartbeat(
                k, len(bars_by_instrument)
            )  # lets a caller show that a slow feature is still working
        for day, (value, available_at) in d.calc(
            sessions, bars_by_instrument[iid], (filings or {}).get(iid)
        ).items():
            rows = out.get(day.replace(day=1))
            if rows is not None:
                rows.append((iid, day, value, available_at))
    for rows in out.values():
        rows.sort(key=lambda r: (r[0], r[1]))
    return out


def complete_months(
    conn: psycopg.Connection, name: str, version: str, dataset_sha256: str
) -> set[date]:
    """The months this feature already has a complete run for on this dataset."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT month FROM feature_run WHERE feature_id=%s AND dataset_sha256=%s AND status='complete'",
            (_id(conn, name, version), dataset_sha256),
        )
    }


def rows_sha256(rows: list[Row]) -> str:
    return hashlib.sha256(
        json.dumps([[i, d.isoformat(), str(v), a.isoformat()] for i, d, v, a in rows]).encode()
    ).hexdigest()


def materialise_month(
    conn: psycopg.Connection, name: str, version: str, month: date, *, dataset_sha256: str, code_commit: str,
    bars_by_instrument: Mapping[int, Mapping[date, SessionBar]], now: datetime,
    filings: Mapping[int, FilingsHistory] | None = None, rows: list[Row] | None = None,
) -> int | None:  # fmt: skip
    """Compute one feature for one calendar month from the supplied history (which must reach back far enough for the warm-up). Returns the run id,
    or None when a complete run for this feature, month and dataset already exists (nothing is written)."""
    now = require_utc(now)
    if month.day != 1:
        raise FeatureError("a feature run is for a whole calendar month: give its first day")
    fid = _id(conn, name, version)
    end = _month_end(month)
    lock = holdout_lock.require(conn)
    if end > lock.development_end:
        raise FeatureError(
            f"{month:%Y-%m} reaches the global holdout (development ends {lock.development_end}): it is not computed"
        )
    if conn.execute(
        "SELECT 1 FROM feature_run WHERE feature_id=%s AND month=%s AND dataset_sha256=%s AND status='complete'",
        (fid, month, dataset_sha256),
    ).fetchone():
        return None
    try:
        rows = rows if rows is not None else compute_rows(name, month, bars_by_instrument, filings)
    except Exception as e:
        conn.execute(
            "INSERT INTO feature_run (feature_id, month, dataset_sha256, code_commit, status, started_at, finished_at, error) VALUES (%s,%s,%s,%s,'failed',%s,%s,%s)",
            (fid, month, dataset_sha256, code_commit, now, now, str(e)),
        )
        raise FeatureError(f"{name}@{version} {month:%Y-%m} failed: {e}") from e
    digest = rows_sha256(rows)
    with conn.transaction():
        run = conn.execute(
            "INSERT INTO feature_run (feature_id, month, dataset_sha256, code_commit, status, rows, result_sha256, started_at, finished_at) VALUES (%s,%s,%s,%s,'complete',%s,%s,%s,%s) RETURNING run_id",
            (fid, month, dataset_sha256, code_commit, len(rows), digest, now, now),
        ).fetchone()[0]  # type: ignore[index]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO feature_value (run_id, instrument_id, day, value, available_at) VALUES (%s,%s,%s,%s,%s)",
                [(run, i, d, v, a) for i, d, v, a in rows],
            )
    return int(run)


def read_features(
    conn: psycopg.Connection, name: str, version: str, dataset_sha256: str, instrument_ids: list[int], start: date, end: date
) -> dict[tuple[int, date], tuple[Decimal, datetime]]:  # fmt: skip
    """Values for exactly this dataset. Every calendar month touched by [start, end] needs a COMPLETE run for it; a month without one raises (and names
    the months), because substituting another snapshot's values would silently change a study's result."""
    fid = _id(conn, name, version)
    runs: dict[date, int] = {}
    missing: list[str] = []
    m = date(start.year, start.month, 1)
    while m <= end:
        row = conn.execute(
            "SELECT run_id FROM feature_run WHERE feature_id=%s AND month=%s AND dataset_sha256=%s AND status='complete'",
            (fid, m, dataset_sha256),
        ).fetchone()
        if row is None:
            missing.append(f"{m:%Y-%m}")
        else:
            runs[m] = int(row[0])
        m = _month_end(m) + timedelta(days=1)
    if missing:
        raise FeatureError(
            f"no completed run of {name}@{version} for dataset {dataset_sha256[:12]} in: {', '.join(missing)}"
        )
    out: dict[tuple[int, date], tuple[Decimal, datetime]] = {}
    for run in runs.values():
        for iid, day, value, at in conn.execute(
            "SELECT instrument_id, day, value, available_at FROM feature_value WHERE run_id=%s AND instrument_id = ANY(%s) AND day BETWEEN %s AND %s",
            (run, instrument_ids, start, end),
        ):
            out[(iid, day)] = (value, at)
    return out


def values_hash(rows: dict[tuple[int, date], tuple[Decimal, datetime]]) -> str:
    """A fingerprint of what was read, for studies that want to pin it."""
    return hashlib.sha256(
        json.dumps(
            [[i, d.isoformat(), str(v), a.isoformat()] for (i, d), (v, a) in sorted(rows.items())]
        ).encode()
    ).hexdigest()

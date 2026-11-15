# ruff: noqa: E501
"""Historical validation of one feature against one data freeze (docs/vti-phase1-spec.md, item F). `validate` computes in memory and writes nothing;
`record` stores the report (insert-only) and, only when it passed, moves a DRAFT feature to USABLE with a status reason that names the report.

A feature passes when ALL of: coverage (valued days / eligible instrument-days after the feature's own warm-up) reaches the minimum (default 90%);
recomputing every month from a freshly opened reader gives the same digest, and every month already materialised for the dataset has the digest the
recomputation gives; and truncating the data at several sessions changes no value for those sessions or earlier (the look-ahead check, on real data).
Eligible days are the days an instrument has a bar; the absent ones are split into warm-up and missing-session (a hole in the window)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from algo.core.clock import require_utc
from algo.data import freeze as freeze_mod
from algo.features import job, registry, store
from algo.features._shared import SessionBar
from algo.features.fundamental import FilingsHistory
from algo.research import holdout_lock

MIN_COVERAGE = Decimal("0.90")
CUTS = 3  # truncation points per instrument for the look-ahead check
Bars = Mapping[int, Mapping[date, SessionBar]]


class ValidationError(Exception):
    pass


def _bars(
    conn: psycopg.Connection,
    f: dict[str, Any],
    lock: holdout_lock.Lock,
    last: date,
    instruments: list[int],
) -> dict[int, dict[date, SessionBar]]:
    reader = job.open_reader(conn, f, lock)
    return {i: store.bars_from_reader(reader, i, last) for i in instruments}


Report = Callable[
    [str, str], None
]  # (phase, message): lets a caller show what a long validation is doing


def _window(
    conn: psycopg.Connection, freeze_id: UUID, first_month: date
) -> tuple[dict[str, Any], holdout_lock.Lock, list[date], list[int], date]:
    f = freeze_mod.get(conn, freeze_id)
    if f is None:
        raise ValidationError(f"no such freeze {freeze_id}")
    lock = holdout_lock.require(conn)
    last = min(f["through_date"], lock.development_end)
    months = job.months_through(first_month, last)
    if not months:
        raise ValidationError(
            f"no whole month from {first_month} to {last} (the holdout is never read)"
        )
    return f, lock, months, [i["instrument_id"] for i in f["items"]], store._month_end(months[-1])


def read_bars(
    conn: psycopg.Connection, freeze_id: UUID, first_month: date, report: Report | None = None
) -> tuple[Bars, Bars]:
    """The freeze's prices read TWICE, independently (the repeat is what proves the same inputs give the same digests). Read once and passed to every
    feature's `validate`, this replaces two full reads per feature."""
    f, lock, _, instruments, end = _window(conn, freeze_id, first_month)
    if report:
        report("reading prices", f"first of two independent reads, {len(instruments)} instruments")
    bars = _bars(conn, f, lock, end, instruments)
    if report:
        report("reading prices", f"second of two independent reads, {len(instruments)} instruments")
    return bars, _bars(conn, f, lock, end, instruments)


def read_filings(
    conn: psycopg.Connection, freeze_id: UUID, first_month: date, report: Report | None = None
) -> tuple[dict[int, FilingsHistory], dict[int, FilingsHistory]]:
    """The freeze's companies' filings (made on or before the development end) read TWICE, independently, like the prices: only fundamental features need them. Read once and passed to
    every fundamental feature's `validate`."""
    f, lock, _, instruments, _ = _window(conn, freeze_id, first_month)
    last = min(f["through_date"], lock.development_end)
    if report:
        report("reading filings", f"first of two independent reads, {len(instruments)} companies")
    first = job.load_filings(conn, instruments, last)
    if report:
        report("reading filings", f"second of two independent reads, {len(instruments)} companies")
    return first, job.load_filings(conn, instruments, last)


def validate(
    conn: psycopg.Connection, name: str, version: str, freeze_id: UUID, first_month: date, *, min_coverage: Decimal = MIN_COVERAGE,
    reads: tuple[Bars, Bars] | None = None, report: Report | None = None,
    filings_reads: tuple[dict[int, FilingsHistory], dict[int, FilingsHistory]] | None = None,
) -> dict[str, Any]:  # fmt: skip
    f, lock, months, instruments, end = _window(conn, freeze_id, first_month)
    d = registry.DEFINITIONS[name]
    bars, again = reads if reads is not None else read_bars(conn, freeze_id, first_month, report)
    last = min(f["through_date"], lock.development_end)
    fa: dict[int, FilingsHistory] | None = None
    fb: dict[int, FilingsHistory] | None = None
    if d.needs_filings:
        fa, fb = (
            filings_reads
            if filings_reads is not None
            else read_filings(conn, freeze_id, first_month, report)
        )
    warm = int(d.manifest["warmup_bars"])
    first_day, rows_by_month, identical = months[0], {}, True
    for k, m in enumerate(months, 1):
        if report:
            report(f"checking {name}", f"recomputing month {k} of {len(months)}")
        rows_by_month[m] = store.compute_rows(name, m, bars, fa)
        identical &= store.rows_sha256(rows_by_month[m]) == store.rows_sha256(
            store.compute_rows(name, m, again, fb)
        )
    fid = store._id(conn, name, version)
    dataset = job.feature_dataset_sha256(conn, freeze_id, instruments, d, last)
    stored = {
        m: sha
        for m, sha in conn.execute(
            "SELECT month, result_sha256 FROM feature_run WHERE feature_id=%s AND dataset_sha256=%s AND status='complete'",
            (fid, dataset),
        )
    }
    checked = [m for m in months if m in stored]
    stored_match = all(stored[m] == store.rows_sha256(rows_by_month[m]) for m in checked)
    valued = {(r[0], r[1]) for rows in rows_by_month.values() for r in rows}
    eligible = warm_absent = missing_absent = 0
    for iid, series in bars.items():
        for k, day in enumerate(sorted(series)):
            if not (first_day <= day <= end):
                continue
            eligible += 1
            if (iid, day) not in valued:
                if k < warm - 1:
                    warm_absent += 1
                else:
                    missing_absent += 1
    after_warmup = eligible - warm_absent
    share = Decimal(len(valued)) / Decimal(after_warmup) if after_warmup else Decimal(0)
    values = [r[2] for rows in rows_by_month.values() for r in rows]
    checks = violations = 0
    sessions = [s for s in registry.sessions_from(bars) if s <= end]
    cut_days = (
        [sessions[len(sessions) * (k + 1) // (CUTS + 1)] for k in range(CUTS)]
        if len(sessions) > CUTS
        else []
    )
    for n, cut in enumerate(cut_days, 1):
        if report:
            report(f"checking {name}", f"look-ahead test {n} of {len(cut_days)} (cut at {cut})")
        short_sessions = [s for s in sessions if s <= cut]
        for iid, series in bars.items():
            history = (fa or {}).get(iid)
            full = d.calc(sessions, series, history)
            short = d.calc(
                short_sessions,
                {x: b for x, b in series.items() if x <= cut},
                history.truncated(cut) if history else None,
            )
            checks += 1
            violations += sum(1 for day in short_sessions if full.get(day) != short.get(day))
    reasons = []
    if share < min_coverage:
        reasons.append(f"coverage {share:.4f} is below the minimum {min_coverage}")
    if not identical:
        reasons.append("recomputing from an independent read gave different values")
    if not stored_match:
        reasons.append("a materialised month differs from the recomputation")
    if violations:
        reasons.append(f"look-ahead: {violations} value(s) changed when later data was removed")
    return {
        "feature": name, "version": version, "family": d.family, "dataset_sha256": dataset, "manifest_sha256": d.manifest_sha256, "freeze": str(freeze_id),
        "months": [f"{m:%Y-%m}" for m in months], "instruments": len(instruments), "min_coverage": str(min_coverage),
        "coverage": {"eligible": eligible, "valued": len(valued), "warmup_absent": warm_absent, "missing_session_absent": missing_absent,
                     "share": f"{share:f}" if share in (0, 1) else f"{share:.6f}"},
        "values": {"min": str(min(values)) if values else None, "max": str(max(values)) if values else None},
        "recompute": {"identical": identical, "months": len(months), "stored_months_checked": len(checked), "stored_match": stored_match},
        "lookahead": {"cuts": [c.isoformat() for c in cut_days], "checks": checks, "violations": violations},
        "passed": not reasons, "reasons": reasons,
    }  # fmt: skip


def record(
    conn: psycopg.Connection,
    name: str,
    version: str,
    dataset_sha256: str,
    report: dict[str, Any],
    *,
    by: str,
    now: datetime,
) -> int:
    """Store the report. A passed report moves a DRAFT feature to USABLE; a failed one changes nothing, and a BLOCKED feature stays BLOCKED
    (a person unblocks it)."""
    now = require_utc(now)
    fid = store._id(conn, name, version)
    row = conn.execute(
        "INSERT INTO feature_validation (feature_id, dataset_sha256, passed, report, created_at, created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING report_id",
        (
            fid,
            dataset_sha256,
            bool(report["passed"]),
            Jsonb(json.loads(json.dumps(report))),
            now,
            by,
        ),
    ).fetchone()
    assert row is not None
    rid = int(row[0])
    if report["passed"] and store.status(conn, name, version) == "DRAFT":
        store.set_status(
            conn,
            name,
            version,
            "USABLE",
            by=by,
            reason=f"validation report {rid}: coverage {report['coverage']['share']}, dataset {dataset_sha256[:12]}",
            now=now,
        )
    return rid

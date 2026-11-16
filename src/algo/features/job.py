# ruff: noqa: E501
"""The feature job (docs/vti-phase1-spec.md, item D): materialise every USABLE feature, month by month, against one data freeze.

The dataset is the freeze (its id, through date, per-instrument checksums and the snapshot hash of its instruments as the database held them
when the freeze was taken), so a rerun against the same freeze is the same dataset and writes nothing for a month already complete.
Months run one feature at a time through `store.materialise_month` (one transaction each); a failure is recorded and does not touch a complete month.
Before each month the job asks `busy`: a paper run, paper orders or the market-hours window pauses it at that boundary, the finished months intact.
It reads prices only through `ResearchReader` and writes only `feature_run` / `feature_value` (through the store)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from algo.data import freeze as freeze_mod
from algo.data.reader import BarReader
from algo.data.readiness import Needs, Readiness, assess
from algo.data.snapshot import snapshot_hash
from algo.features import registry, store
from algo.features._shared import SessionBar
from algo.features.fundamental import FilingsHistory
from algo.research import holdout_lock
from algo.research.holdout_lock import ResearchReader
from algo.research.slot import busy_reason  # noqa: F401  (re-exported: the script and the tests call job.busy_reason)
from algo.screener.snapshot import quarters_since

IST = ZoneInfo("Asia/Kolkata")


class JobRefused(Exception):
    pass


@dataclass
class Report:
    status: str = "complete"  # complete | paused | failed
    computed: list[tuple[str, str]] = field(default_factory=list)  # (feature, YYYY-MM)
    already: int = 0
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # features that are not USABLE
    paused_because: str = ""


def months_through(first: date, end: date) -> list[date]:
    """First days of every calendar month from `first`'s whose last day is on or before `end`."""
    out, m = [], date(first.year, first.month, 1)
    while store._month_end(m) <= end:
        out.append(m)
        m = store._month_end(m) + timedelta(days=1)
    return out


def dataset_sha256(conn: psycopg.Connection, freeze_id: UUID, instruments: list[int]) -> str:
    f = freeze_mod.get(conn, freeze_id)
    if f is None:
        raise JobRefused(f"no such freeze {freeze_id}")
    items = [[i["instrument_id"], i["row_count"], i["sha256"]] for i in f["items"]]
    manifest = {
        "price_source": f["source"], "freeze": str(freeze_id), "through": f["through_date"].isoformat(),
        "items_sha256": hashlib.sha256(json.dumps(items).encode()).hexdigest(),
        "data_hash": snapshot_hash(conn, f["source"], instruments, f["taken_at"]),
    }  # fmt: skip
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def load_filings(
    conn: psycopg.Connection, instruments: list[int], until: date
) -> dict[int, FilingsHistory]:
    """Every filing of these companies made on or before `until` (an Indian calendar day), by company. A filing after `until` is never loaded, so the holdout's filings are never held."""
    by_company: dict[int, dict[str, list[Any]]] = {}
    for (iid, basis), quarters in quarters_since(conn, date(2000, 1, 1), instruments).items():
        kept = [x for x in quarters if x.filed_at.astimezone(IST).date() <= until]
        if kept:
            by_company.setdefault(iid, {})[basis] = kept
    return {iid: FilingsHistory(b) for iid, b in by_company.items()}


def fundamentals_sha256(conn: psycopg.Connection, instruments: list[int], until: date) -> str:
    """The identity of the filings a fundamental feature reads: which filings (by their raw-file hash), of which company, period and basis, filed when, up to `until`."""
    rows = conn.execute(
        "SELECT filing_id, instrument_id, basis, period_end, filed_at, raw_sha256 FROM fundamental_filing"
        " WHERE instrument_id = ANY(%s) AND (filed_at AT TIME ZONE 'Asia/Kolkata')::date <= %s ORDER BY filing_id",
        (instruments, until),
    ).fetchall()
    return hashlib.sha256(
        json.dumps(
            [[r[0], r[1], r[2], r[3].isoformat(), r[4].isoformat(), r[5]] for r in rows]
        ).encode()
    ).hexdigest()


def feature_dataset_sha256(
    conn: psycopg.Connection,
    freeze_id: UUID,
    instruments: list[int],
    d: registry.FeatureDef,
    until: date,
) -> str:
    """The data identity of one feature: the prices for a price feature, the prices AND the filings (up to `until`) for a fundamental one."""
    prices = dataset_sha256(conn, freeze_id, instruments)
    if not d.needs_filings:
        return prices
    return hashlib.sha256(
        json.dumps(
            {"prices": prices, "filings": fundamentals_sha256(conn, instruments, until)},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def open_reader(
    conn: psycopg.Connection, f: dict[str, Any], lock: holdout_lock.Lock
) -> ResearchReader:
    """The only reader a feature computation uses: pinned to what the database held when the freeze was taken, and unable to see the holdout."""
    inner = BarReader(
        conn,
        source=f["source"],
        publish_lag=timedelta(0) if f["source"] == "kite" else timedelta(hours=3),
        known_at=f["taken_at"],
    )
    return ResearchReader(inner, lock)


def run(
    conn: psycopg.Connection, freeze_id: UUID, first_month: date, now: datetime, code_commit: str,
    *, busy: Callable[[datetime], str | None] = lambda _: None,
    ready: Callable[[psycopg.Connection, Needs], Readiness] = assess,
    progress: Callable[..., None] | None = None,
) -> Report:  # fmt: skip
    f = freeze_mod.get(conn, freeze_id)
    if f is None:
        raise JobRefused(f"no such freeze {freeze_id}")
    lock = holdout_lock.require(conn)
    last = min(f["through_date"], lock.development_end)  # never a day of the holdout
    months = months_through(first_month, last)
    instruments = [i["instrument_id"] for i in f["items"]]
    if months:
        verdict = ready(
            conn, Needs(day=store._month_end(months[-1]), instruments=tuple(instruments))
        )
        if not verdict.ready:
            raise JobRefused("the input data is not ready: " + verdict.summary())
    out = Report()
    usable = []
    for name, d in registry.DEFINITIONS.items():
        if store.status(conn, name, d.version) == "USABLE":
            usable.append((name, d.version))
        else:
            out.skipped.append(name)
    if not months or not usable:
        return out
    reader = open_reader(conn, f, lock)
    shas = {
        n: feature_dataset_sha256(conn, freeze_id, instruments, registry.DEFINITIONS[n], last)
        for n, _ in usable
    }
    filings: dict[int, FilingsHistory] | None = None
    bars: dict[int, dict[date, SessionBar]] | None = None
    steps, finished = len(months) * len(usable), 0
    if progress:
        progress(
            "starting", f"{len(usable)} features over {len(months)} months", done=0, total=steps
        )
    for name, version in usable:
        by_month: dict[date, list[store.Row]] | None = None
        tried = False
        for month in months:
            if (why := busy(now)) is not None:
                out.status, out.paused_because = "paused", why
                return out
            if registry.DEFINITIONS[name].needs_filings and filings is None:
                if progress:
                    progress(
                        "reading filings",
                        f"{len(instruments)} companies",
                        done=finished,
                        total=steps,
                    )
                filings = load_filings(conn, instruments, last)
            if bars is None:
                if progress:
                    progress(
                        "reading prices", f"{len(instruments)} instruments", done=0, total=steps
                    )
                bars = {i: store.bars_from_reader(reader, i, last) for i in instruments}
            if progress:
                progress(f"computing {name}", f"month {month:%Y-%m}", done=finished, total=steps)
            if not tried:
                # one pass over the history for every month still to do, not one pass per month; if it fails, each month is tried (and recorded as failed) on its own below
                tried = True
                pending = [
                    m
                    for m in months
                    if m not in store.complete_months(conn, name, version, shas[name])
                ]
                if pending:
                    try:
                        by_month = store.compute_rows_by_month(name, pending, bars, filings)
                    except Exception:
                        by_month = None
            try:
                run_id = store.materialise_month(
                    conn, name, version, month, dataset_sha256=shas[name], code_commit=code_commit,
                    bars_by_instrument=bars, now=now, filings=filings,
                    rows=None if by_month is None else by_month.get(month),
                )  # fmt: skip
            except store.FeatureError as e:
                out.failed.append(str(e))
                out.status = "failed"
                finished += 1
                continue
            finished += 1
            if run_id is None:
                out.already += 1
            else:
                out.computed.append((name, f"{month:%Y-%m}"))
    return out

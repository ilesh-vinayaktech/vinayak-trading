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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg

from algo.data import freeze as freeze_mod
from algo.data.reader import BarReader
from algo.data.readiness import Needs, Readiness, assess
from algo.data.snapshot import snapshot_hash
from algo.features import registry, store
from algo.features._shared import SessionBar
from algo.research import holdout_lock
from algo.research.holdout_lock import ResearchReader

IST = ZoneInfo("Asia/Kolkata")
MARKET = (time(9, 0), time(15, 45))  # the live feed and paper orders run in this window
YIELD_TO = ("run_paper.py", "paper_orders.py")  # processes that outrank the feature job


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


def busy_reason(now: datetime, commandlines: Iterable[str]) -> str | None:
    """Why the machine belongs to something else right now, or None."""
    for line in commandlines:
        for name in YIELD_TO:
            if name in line:
                return f"{name} is running"
    local = now.astimezone(IST)
    if local.weekday() < 5 and MARKET[0] <= local.time() <= MARKET[1]:
        return "market hours"
    return None


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


def run(
    conn: psycopg.Connection, freeze_id: UUID, first_month: date, now: datetime, code_commit: str,
    *, busy: Callable[[datetime], str | None] = lambda _: None,
    ready: Callable[[psycopg.Connection, Needs], Readiness] = assess,
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
    reader = ResearchReader(
        BarReader(conn, source=f["source"], publish_lag=timedelta(0) if f["source"] == "kite" else timedelta(hours=3), known_at=f["taken_at"]),
        lock,
    )  # fmt: skip
    sha = dataset_sha256(conn, freeze_id, instruments)
    bars: dict[int, dict[date, SessionBar]] | None = None
    for month in months:
        for name, version in usable:
            if (why := busy(now)) is not None:
                out.status, out.paused_because = "paused", why
                return out
            if bars is None:
                bars = {i: store.bars_from_reader(reader, i, last) for i in instruments}
            try:
                run_id = store.materialise_month(
                    conn, name, version, month, dataset_sha256=sha, code_commit=code_commit,
                    bars_by_instrument=bars, now=now,
                )  # fmt: skip
            except store.FeatureError as e:
                out.failed.append(str(e))
                out.status = "failed"
                continue
            if run_id is None:
                out.already += 1
            else:
                out.computed.append((name, f"{month:%Y-%m}"))
    return out

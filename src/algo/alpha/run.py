# ruff: noqa: E501
"""Run alpha discovery on stored data: the USABLE features materialised for a data freeze, the development-window prices through the guarded reader.

Callers: tests/integration/alpha/test_run.py and scripts/discover_alpha.py. It reads data_freeze, feature_run, feature_value and bar_1d and writes
alpha_hypothesis (through algo.alpha.registry). User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and
@plan.md ... keep things finishing with test".

  * Only features whose status is USABLE are examined: a feature that has not been validated is not a basis for a hypothesis.
  * Prices come from the ResearchReader, which cannot return a holdout day, and no observation's return window may end after the development end.
  * The universe is the freeze's instruments. That is NOT point-in-time Nifty 200 membership; the caller states so in `context`, and it is stored
    with every hypothesis. Nothing found here is evidence about the Nifty 200 until membership is strict-eligible."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

from algo.alpha import discover, registry
from algo.data import freeze as freeze_mod
from algo.features import job, store
from algo.features import registry as feature_registry
from algo.research import holdout_lock


class DiscoveryError(Exception):
    pass


def measure(
    conn: psycopg.Connection,
    freeze_id: UUID,
    first_month: date,
    *,
    horizons: Sequence[int],
    min_names: int,
    report: Callable[[str, str], None] | None = None,
) -> list[discover.Evidence]:
    f = freeze_mod.get(conn, freeze_id)
    if f is None:
        raise DiscoveryError(f"no such freeze {freeze_id}")
    lock = holdout_lock.require(conn)
    last = min(f["through_date"], lock.development_end)
    months = job.months_through(first_month, last)
    if not months:
        raise DiscoveryError(f"no whole development month from {first_month} to {last}")
    instruments = [i["instrument_id"] for i in f["items"]]
    usable = [
        (name, d.version)
        for name, d in feature_registry.DEFINITIONS.items()
        if store.status(conn, name, d.version) == "USABLE"
    ]
    if not usable:
        raise DiscoveryError("no USABLE feature to examine")
    reader = job.open_reader(conn, f, lock)
    if report:
        report("reading prices", f"{len(instruments)} instruments")
    bars = {i: store.bars_from_reader(reader, i, last) for i in instruments}
    closes: dict[int, dict[date, Decimal]] = {
        i: {d: b.close for d, b in series.items()} for i, series in bars.items()
    }
    sessions = [d for d in feature_registry.sessions_from(bars) if d <= last]
    end = store._month_end(months[-1])
    features: dict[tuple[str, str], dict[tuple[int, date], Decimal]] = {}
    for k, (name, version) in enumerate(usable, 1):
        if report:
            report("loading features", f"{name} ({k} of {len(usable)})")
        sha = job.feature_dataset_sha256(
            conn, freeze_id, instruments, feature_registry.DEFINITIONS[name], last
        )  # each feature is read back under its own data identity
        rows = store.read_features(conn, name, version, sha, instruments, months[0], end)
        features[(name, version)] = {key: value for key, (value, _available_at) in rows.items()}
    if report:
        report("testing", f"{len(usable)} features at {len(horizons)} horizons")
    return discover.discover(
        features,
        closes,
        sessions,
        horizons=horizons,
        last_allowed=last,
        min_names=min_names,
        heartbeat=(lambda name, h, k, n: report("testing", f"{name} at {h} days (test {k} of {n})"))
        if report
        else None,
    )


def batch_dataset_sha256(
    conn: psycopg.Connection, freeze_id: UUID, instruments: list[int], until: date
) -> str:
    """The data identity of a discovery batch: the identity every usable feature shares (prices, for price features), or a hash of the distinct identities when fundamental features, which
    also read filings, are among them."""
    shas = sorted(
        {
            job.feature_dataset_sha256(conn, freeze_id, instruments, d, until)
            for name, d in feature_registry.DEFINITIONS.items()
            if store.status(conn, name, d.version) == "USABLE"
        }
    )
    if not shas:
        return job.dataset_sha256(conn, freeze_id, instruments)
    return shas[0] if len(shas) == 1 else hashlib.sha256(json.dumps(shas).encode()).hexdigest()


def run_discovery(
    conn: psycopg.Connection,
    freeze_id: UUID,
    first_month: date,
    now: datetime,
    *,
    horizons: Sequence[int],
    min_names: int,
    context: dict[str, Any] | None = None,
    report: Callable[[str, str], None] | None = None,
) -> list[int]:
    """Measure, then record the whole batch (failures included). Returns the hypothesis ids."""
    evidences = measure(
        conn, freeze_id, first_month, horizons=horizons, min_names=min_names, report=report
    )
    f = freeze_mod.get(conn, freeze_id)
    assert f is not None
    sha = batch_dataset_sha256(
        conn,
        freeze_id,
        [i["instrument_id"] for i in f["items"]],
        min(f["through_date"], holdout_lock.require(conn).development_end),
    )
    if report:
        report("recording", f"{len(evidences)} results, failures included")
    return registry.record(conn, evidences, sha, now, context=context)

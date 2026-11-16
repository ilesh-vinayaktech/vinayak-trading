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


def _liquid(
    conn: psycopg.Connection,
    freeze_id: UUID,
    instruments: list[int],
    last: date,
    first_month: date,
    end: date,
    top: int,
) -> dict[date, frozenset[int]]:
    """The `top` most traded names of each day, by the 20-day traded value KNOWN that day (a value uses only bars up to the day, so the choice looks at nothing later); ties go to the lower id."""
    d = feature_registry.DEFINITIONS["traded_value_20d"]
    if store.status(conn, "traded_value_20d", d.version) != "USABLE":
        raise DiscoveryError("a liquid universe needs traded_value_20d to be USABLE")
    sha = job.feature_dataset_sha256(conn, freeze_id, instruments, d, last)
    by_day: dict[date, list[tuple[Decimal, int]]] = {}
    for (iid, day), (value, _available_at) in store.read_features(
        conn, "traded_value_20d", d.version, sha, instruments, first_month, end
    ).items():
        by_day.setdefault(day, []).append((value, iid))
    return {
        day: frozenset(i for _, i in sorted(v, key=lambda t: (-t[0], t[1]))[:top])
        for day, v in by_day.items()
    }


def _numbered(
    report: Callable[[str, str], None], offset: int, total: int
) -> Callable[[str, int, int, int], None]:
    """A per-feature heartbeat that numbers its tests across ALL the features ('test 14 of 108')."""

    def beat(name: str, horizon: int, k: int, _n: int) -> None:
        report("testing", f"{name} at {horizon} days (test {offset + k} of {total})")

    return beat


def measure(
    conn: psycopg.Connection,
    freeze_id: UUID,
    first_month: date,
    *,
    horizons: Sequence[int],
    min_names: int,
    report: Callable[[str, str], None] | None = None,
    liquid_top: int | None = None,
) -> list[discover.Evidence]:
    """`liquid_top`, when given, tests only the `liquid_top` most traded names each day (by the 20-day traded value known that day), the others left out of that day's cross-section."""
    if liquid_top is not None and liquid_top < 1:
        raise DiscoveryError("a liquid universe needs at least 1 name a day")
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
    del bars  # the full bars are not needed again: the closes and the sessions are all the tests use, and holding both would double the memory
    end = store._month_end(months[-1])
    eligible: dict[date, frozenset[int]] | None = None
    if liquid_top is not None:
        if report:
            report(
                "liquid universe",
                f"the {liquid_top} most traded names of each day, by 20-day traded value",
            )
        eligible = _liquid(conn, freeze_id, instruments, last, months[0], end, liquid_top)
    horizons_sorted = sorted(horizons)
    total = len(usable) * len(horizons_sorted)
    out: list[discover.Evidence] = []
    # one feature at a time: its values are read, tested at every horizon and dropped, so memory holds one feature, not all of them. `discover.discover` works through a
    # sorted plan, so testing the sorted features one by one gives exactly the evidence, in exactly the order, of testing them all at once.
    for k, (name, version) in enumerate(sorted(usable), 1):
        if report:
            report("loading features", f"{name} ({k} of {len(usable)})")
        sha = job.feature_dataset_sha256(
            conn, freeze_id, instruments, feature_registry.DEFINITIONS[name], last
        )  # each feature is read back under its own data identity
        rows = store.read_features(conn, name, version, sha, instruments, months[0], end)
        values = {key: value for key, (value, _available_at) in rows.items()}
        del rows
        offset = (k - 1) * len(horizons_sorted)
        out += discover.discover(
            {(name, version): values},
            closes,
            sessions,
            horizons=horizons_sorted,
            last_allowed=last,
            min_names=min_names,
            heartbeat=_numbered(report, offset, total) if report else None,
            eligible=eligible,
        )
    return out


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
    liquid_top: int | None = None,
) -> list[int]:
    """Measure, then record the whole batch (failures included). Returns the hypothesis ids."""
    evidences = measure(
        conn,
        freeze_id,
        first_month,
        horizons=horizons,
        min_names=min_names,
        report=report,
        liquid_top=liquid_top,
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

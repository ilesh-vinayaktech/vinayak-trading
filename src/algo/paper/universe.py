# ruff: noqa: E501
"""Who the strategy may trade today: the Nifty 200 constituents from the latest list in the lake (raw/niftyindices/nifty200_list).

Live paper trading has no use for point-in-time history: the list as of today IS the index. A missing list, or one older than
`max_age_days`, is refused (the index is reconstituted twice a year, so an old file may name the wrong stocks); symbols that
cannot be mapped to an instrument are reported in the metadata, never silently dropped."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from algo.data.store.instruments import InstrumentRepo, NotFoundError
from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import IntervalMembership

FOREVER = date(2000, 1, 1)


class UniverseError(Exception):
    pass


def current_nifty200(
    conn: psycopg.Connection, lake_root: Path, day: date, *, max_age_days: int = 75
) -> tuple[IntervalMembership, dict[str, Any]]:
    folders = sorted(
        (date.fromisoformat(p.name[3:]), p)
        for p in (lake_root / "raw/niftyindices/nifty200_list").glob("dt=*")
        if date.fromisoformat(p.name[3:]) <= day
    )
    if not folders:
        raise UniverseError(f"no Nifty 200 list in the lake on or before {day}")
    listed_on, folder = folders[-1]
    if (day - listed_on).days > max_age_days:
        raise UniverseError(
            f"the newest Nifty 200 list is {(day - listed_on).days} days old (from {listed_on}); refresh it"
        )
    newest = sorted(folder.glob("v*.bin"), key=lambda p: int(p.stem[1:]))[-1]
    rows = list(csv.DictReader(io.StringIO(newest.read_bytes().decode("utf-8-sig"))))
    repo, ids, unmatched = InstrumentRepo(conn), [], []
    for r in rows:
        try:
            ids.append(repo.resolve("nse", r["Symbol"], day))
        except NotFoundError:
            unmatched.append(r["Symbol"])
    meta = {
        "list_date": str(listed_on),
        "listed": len(rows),
        "mapped": len(ids),
        "unmatched": unmatched,
    }
    return IntervalMembership([Interval(i, FOREVER, None) for i in ids]), meta

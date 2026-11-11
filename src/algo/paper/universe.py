# ruff: noqa: E501
"""Who the strategy may trade today: the constituents of an index, from the latest list(s) in the lake (raw/niftyindices/<list>).

The universe is chosen by name (UNIVERSES); the bigger ones are unions of lists (Nifty 100 = Nifty 50 + Next 50). Live paper
trading has no use for point-in-time history: the list as of today IS the index. A missing list, or one older than
`max_age_days`, is refused (indices are reconstituted twice a year, so an old file may name the wrong stocks); symbols that
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


UNIVERSES: dict[str, tuple[str, tuple[str, ...]]] = {  # key -> (label, lists in the lake)
    "nifty50": ("Nifty 50", ("nifty50_list",)),
    "nifty100": ("Nifty 100", ("nifty50_list", "niftynext50_list")),
    "nifty200": ("Nifty 200", ("nifty200_list",)),
    "midcap100": ("Nifty Midcap 100", ("niftymidcap100_list",)),
    "nifty500": ("Nifty 500", ("nifty500_list",)),
}


class UniverseError(Exception):
    pass


def _newest(lake_root: Path, name: str, day: date, max_age_days: int) -> tuple[date, Path]:
    folders = sorted(
        (date.fromisoformat(p.name[3:]), p)
        for p in (lake_root / "raw/niftyindices" / name).glob("dt=*")
        if date.fromisoformat(p.name[3:]) <= day
    )
    if not folders:
        raise UniverseError(f"no {name} in the lake on or before {day}")
    listed_on, folder = folders[-1]
    if (day - listed_on).days > max_age_days:
        raise UniverseError(
            f"the newest {name} is {(day - listed_on).days} days old (from {listed_on}); refresh it"
        )
    return listed_on, sorted(folder.glob("v*.bin"), key=lambda p: int(p.stem[1:]))[-1]


def current_universe(
    conn: psycopg.Connection,
    lake_root: Path,
    day: date,
    key: str = "nifty200",
    *,
    max_age_days: int = 75,
) -> tuple[IntervalMembership, dict[str, Any]]:
    if key not in UNIVERSES:
        raise UniverseError(f"unknown universe {key!r}")
    repo = InstrumentRepo(conn)
    lists: dict[str, str] = {}
    ids: list[int] = []
    listed, unmatched = 0, []
    for name in UNIVERSES[key][1]:
        listed_on, newest = _newest(lake_root, name, day, max_age_days)
        lists[name] = str(listed_on)
        for r in csv.DictReader(io.StringIO(newest.read_bytes().decode("utf-8-sig"))):
            listed += 1
            try:
                iid = repo.resolve("nse", r["Symbol"], day)
            except NotFoundError:
                unmatched.append(r["Symbol"])
                continue
            if iid not in ids:
                ids.append(iid)
    meta = {
        "universe": key,
        "lists": lists,
        "listed": listed,
        "mapped": len(ids),
        "unmatched": unmatched,
    }
    return IntervalMembership([Interval(i, FOREVER, None) for i in ids]), meta

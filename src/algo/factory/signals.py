# ruff: noqa: E501
"""One stock's buy/sell decisions under a generated strategy definition, for the Data Explorer chart.

Callers: algo.api.strategy_routes (GET /api/strategies/definitions/{id}/{version}/signals) and tests/unit/factory/test_signals.py. Nothing similar exists: algo.strategies.signals and
screener_signals replay a coded strategy over one stock's own bars, but a definition ranks a stock AGAINST THE OTHERS each day (TOP_PERCENT / BOTTOM_PERCENT), so it needs every stock's
stored feature value for the day. User's instruction: "they are not visible in stratergy dropdown in Data explorer chart".

The rule is the interpreter's own (`_cross_sections`, `_holds`, the rebalance cadence) applied to one name; it ignores the limit on how many stocks are held, the choice among stocks that qualify
on the same day, and index membership. Stored feature values are used to their last day (the development end); later days are computed on the spot from price bars and kept nowhere (owner: no storing, no comparing)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from math import ceil

import psycopg

from algo.data import freeze as freeze_mod
from algo.data.reader import AdjBar
from algo.factory.dsl import StrategyDef
from algo.factory.interpreter import Cadence, _cross_sections, _holds, _session_bars
from algo.features import job, store
from algo.features import registry as feature_registry
from algo.research import holdout_lock

NOTES = [
    "Decisions only: this is not a backtest and shows no profit or loss.",
    "A definition ranks each stock against all the others that day, so this uses the stored feature values of every stock. It ignores the limit on how many stocks are held, the choice among stocks that qualify on the same day, and index membership.",
    "Up to the end of 2024 the values are the stored ones; after that they are computed on the spot from price bars for the names that were most traded at the end of 2024, and kept nowhere. A decision is made after the day's close and filled at the next session's open.",
]


@dataclass(frozen=True)
class Decision:
    day: date
    ready: bool  # the stock has a value for every feature the rule reads
    action: str | None  # "BUY" or "SELL", decided after this day's close
    reason: str | None
    holding_after: bool


def features_used(defn: StrategyDef) -> list[str]:
    return sorted({c.feature for c in defn.entry.conditions() + defn.exit.conditions()})


def decide(
    defn: StrategyDef,
    values: dict[str, dict[date, dict[int, Decimal]]],
    iid: int,
    days: list[date],
    *,
    held: bool = False,
    after: date | None = None,
) -> list[Decision]:
    """`values[feature][day][instrument]` is the value; `days` are the stock's sessions in order. The stock starts not held, or `held` when continuing a stored series whose last day was `after`
    (the rebalance period of that day is then already decided)."""
    cadence, out = Cadence(defn.rebalance), []
    if after is not None:
        cadence.due(after)
    needed = features_used(defn)
    for d in days:
        per = {f: values.get(f, {}).get(d, {}) for f in needed}
        ready = {
            i: {f: per[f][i] for f in needed}
            for i in per[needed[0]]
            if all(i in per[f] for f in needed)
        }
        if iid not in ready:
            out.append(Decision(d, False, None, None, held))
            continue
        action = reason = None
        if cadence.due(d):
            cross = _cross_sections(defn, ready)
            if held and _holds(defn.exit, ready[iid], iid, cross):
                action, reason, held = "SELL", "the exit rule holds", False
            elif not held and _holds(defn.entry, ready[iid], iid, cross):
                action, reason, held = "BUY", "the entry rule holds", True
        out.append(Decision(d, True, action, reason, held))
    return out


class SignalsError(Exception):
    pass


LIQUID_TOP = 200  # each day the stock is ranked against the 200 most traded names (by 20-day traded value known that day), as the research runs do
LIQUID_FEATURE = "traded_value_20d"


def _months(start: date, end: date) -> list[tuple[date, date]]:
    out, m = [], date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        out.append((max(m, start), min(nxt - timedelta(days=1), end)))
        m = nxt
    return out


@dataclass(frozen=True)
class Stored:
    """What is stored for the rule's features: the values for the asked days that fall inside the stored window, the window itself, and the most traded names on its first and last day (the
    universe the days outside the window are computed for)."""

    values: dict[str, dict[date, dict[int, Decimal]]]
    first: date
    last: date
    head_universe: set[int]
    tail_universe: set[int]


def _stored_window(
    conn: psycopg.Connection, shas: dict[str, tuple[str, str]], last: date
) -> tuple[date, date] | None:
    """The newest unbroken run of months for which EVERY feature (name -> (version, dataset)) has a completed run, as (first day, last day cut to `last`); None when there is none."""
    common: set[date] | None = None
    for name, (version, sha) in shas.items():
        months = {
            r[0]
            for r in conn.execute(
                "SELECT month FROM feature_run WHERE feature_id=%s AND dataset_sha256=%s AND status='complete'",
                (store._id(conn, name, version), sha),
            )
        }
        common = months if common is None else common & months
    if not common:
        return None
    top = max(common)
    first = top
    while True:
        prev = date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)
        if prev not in common:
            break
        first = prev
    return first, min(store._month_end(top), last)


def load_values(
    conn: psycopg.Connection,
    defn: StrategyDef,
    start: date,
    end: date,
    *,
    top: int = LIQUID_TOP,
    always: int | None = None,
) -> Stored:
    """The STORED values of every feature the rule reads, month by month, kept only for each day's `top` most traded stocks (and for `always`, the stock being drawn, whatever its rank), for the part of
    `start`..`end` that lies inside the stored window. Streaming by month keeps ten years in memory. The holdout is never part of the stored window (it ends at the development end)."""
    lock = holdout_lock.require(conn)
    row = conn.execute(
        "SELECT freeze_id FROM data_freeze ORDER BY taken_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise SignalsError("there is no data freeze, so no stored feature values")
    f = freeze_mod.get(conn, row[0])
    assert f is not None
    last = min(f["through_date"], lock.development_end)
    instruments = [i["instrument_id"] for i in f["items"]]
    names = [LIQUID_FEATURE, *features_used(defn)]
    ident = {
        n: (
            feature_registry.DEFINITIONS[n].version,
            job.feature_dataset_sha256(
                conn, row[0], instruments, feature_registry.DEFINITIONS[n], last
            ),
        )
        for n in names
    }
    window = _stored_window(conn, ident, last)
    if window is None:
        raise SignalsError(
            f"no stored values of {', '.join(names)} for the latest data: run scripts/compute_features.py"
        )
    first, stored_last = window
    tv_version, tv_sha = ident[LIQUID_FEATURE]

    def liquid_of(lo: date, hi: date) -> dict[date, set[int]]:
        by_day: dict[date, list[tuple[Decimal, int]]] = {}
        for (iid, day), (value, _at) in store.read_features(
            conn, LIQUID_FEATURE, tv_version, tv_sha, instruments, lo, hi
        ).items():
            by_day.setdefault(day, []).append((value, iid))
        return {
            day: {i for _, i in sorted(v, key=lambda t: (-t[0], t[1]))[:top]}
            for day, v in by_day.items()
        }

    out: dict[str, dict[date, dict[int, Decimal]]] = {n: {} for n in names[1:]}
    try:
        head = liquid_of(first, store._month_end(first))
        tail = liquid_of(date(stored_last.year, stored_last.month, 1), stored_last)
        lo, hi = max(start, first), min(end, stored_last)
        if lo <= hi:
            for mlo, mhi in _months(lo, hi):
                liquid = liquid_of(mlo, mhi)
                for name in names[1:]:
                    version, sha = ident[name]
                    for (iid, day), (value, _at) in store.read_features(
                        conn, name, version, sha, instruments, mlo, mhi
                    ).items():
                        if iid in liquid.get(day, ()) or iid == always:
                            out[name].setdefault(day, {})[iid] = value
    except store.FeatureError as e:
        raise SignalsError(str(e)) from e
    return Stored(out, first, stored_last, head[min(head)], tail[max(tail)])


def tail_values(
    defn: StrategyDef,
    universe: set[int],
    after: date,
    to: date,
    bars_of: Callable[[int, date, date], list[AdjBar]],
) -> dict[str, dict[date, dict[int, Decimal]]]:
    """Values for the days in (`after`, `to`], computed NOW from price bars for `universe` and kept nowhere: the same feature functions the stored values came from. `bars_of(instrument, from, to)`
    gives adjusted daily bars; enough history before `after` is asked for to warm every feature up."""
    needed = features_used(defn)
    warm = max(int(feature_registry.DEFINITIONS[n].manifest["warmup_bars"]) for n in needed)
    first = after - timedelta(days=ceil(warm * 7 / 5) + 30)
    sbars = {i: _session_bars(bars_of(i, first, to)) for i in sorted(universe)}
    sbars = {i: b for i, b in sbars.items() if b}
    sessions = feature_registry.sessions_from(sbars)
    out: dict[str, dict[date, dict[int, Decimal]]] = {n: {} for n in needed}
    for name in needed:
        for i, b in sbars.items():
            for day, (value, _at) in (
                feature_registry.DEFINITIONS[name].compute(sessions, b).items()
            ):
                if after < day <= to:
                    out[name].setdefault(day, {})[i] = value
    return out


def compute(
    conn: psycopg.Connection,
    defn: StrategyDef,
    iid: int,
    days: list[date],
    bars_of: Callable[[int, date, date], list[AdjBar]],
    *,
    held: bool = False,
    after: date | None = None,
) -> list[Decision]:
    """The decisions for `days` (the stock's consecutive sessions): stored feature values inside the stored window, values computed in memory for the days before and after it, then the rule. With
    `held` and `after` it continues a stored series. Nothing is written here."""
    if not days:
        return []
    start, end = days[0], days[-1]
    stored = load_values(conn, defn, start, end, always=iid)
    values, one_day = stored.values, timedelta(days=1)
    if start < stored.first:
        head = tail_values(
            defn,
            stored.head_universe | {iid},
            start - one_day,
            min(end, stored.first - one_day),
            bars_of,
        )
        for name, per_day in head.items():
            values.setdefault(name, {}).update(per_day)
    if end > stored.last:
        tail = tail_values(
            defn, stored.tail_universe | {iid}, max(start - one_day, stored.last), end, bars_of
        )
        for name, per_day in tail.items():
            values.setdefault(name, {}).update(per_day)
    return decide(defn, values, iid, days, held=held, after=after)

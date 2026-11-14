# ruff: noqa: E501
"""May a strategy decide on `day`? One answer with reasons, from the data the reader would serve.

Global blockers (`reasons`, each one blocks on its own):
  NO_DATA / STALE   no bars at all, or the newest bar is more than `max_sessions_behind` sessions before `day`
                    (sessions, never calendar days: a weekend or a holiday is not behind)
  PROVIDER          the price source in force is not the one the strategy expects
  QUARANTINED / MISSING_DAY / THIN_DAY   the completeness findings (algo.data.quality.completeness)
  COVERAGE          too few of the requested instruments are individually ready
Per instrument (`unready`, reported, not blocking by themselves): UNKNOWN_INSTRUMENT, NO_BAR on `day`,
SHORT_HISTORY (fewer than `warmup_bars` bars on or before `day`).
A missing bar is reported as missing and never filled: the reader returns no bar for it.
Not checked yet: features (there is no feature store) and intraday freshness in seconds (daily bars only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from algo.data.price_source import price_source
from algo.data.quality.completeness import check


@dataclass(frozen=True)
class Needs:
    day: date  # the session whose close the decision uses
    instruments: tuple[int, ...] = ()
    warmup_bars: int = 0
    window_days: int = 30  # calendar days looked at for gaps
    max_sessions_behind: int = 0
    expected_source: str | None = None  # "kite" | "bhavcopy"
    min_coverage: Decimal = Decimal("0.95")  # share of the requested instruments that must be ready


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str
    instrument_id: int | None = None


@dataclass
class Readiness:
    reasons: list[Reason] = field(default_factory=list)
    unready: list[Reason] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.reasons

    def summary(self) -> str:
        return "; ".join(f"{r.code}: {r.detail}" for r in self.reasons)


def _holidays(conn: psycopg.Connection) -> set[date]:
    return {
        r[0]
        for r in conn.execute(
            "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status"
            " FROM partition_load ORDER BY source, dataset, partition, id DESC)"
            " SELECT partition FROM l WHERE status='not_published'"
        )
    }


def assess(conn: psycopg.Connection, needs: Needs) -> Readiness:
    out = Readiness()
    source = price_source()
    bar_source = "kite" if source == "kite" else "nse"
    if needs.expected_source is not None and needs.expected_source != source:
        out.reasons.append(
            Reason(
                "PROVIDER",
                f"the price source in force is {source}, the strategy expects {needs.expected_source}",
            )
        )
    row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE source=%s",
        (bar_source,),
    ).fetchone()
    newest = row[0] if row else None
    if newest is None:
        out.reasons.append(Reason("NO_DATA", f"no {bar_source} daily bars at all"))
        return out
    holidays = _holidays(conn)
    behind = sum(
        1
        for i in range(1, (needs.day - newest).days + 1)
        if (d := newest + timedelta(days=i)).weekday() < 5 and d not in holidays
    )
    if behind > needs.max_sessions_behind:
        out.reasons.append(
            Reason(
                "STALE",
                f"the newest {bar_source} bar is {newest}, {behind} session(s) before {needs.day}"
                f" (at most {needs.max_sessions_behind} allowed)",
            )
        )
    report = check(conn, needs.day - timedelta(days=needs.window_days))
    out.reasons += [
        Reason("QUARANTINED", f"the NSE file of {d} was refused") for d in report.quarantined
    ]
    out.reasons += [
        Reason("MISSING_DAY", f"no NSE bars on {d} and it is not a recorded holiday")
        for d in report.missing_days
        if d <= needs.day
    ]
    out.reasons += [
        Reason("THIN_DAY", f"{d}: {n} NSE bars against about {avg}")
        for d, n, avg in report.thin_days
        if d <= needs.day
    ]
    if needs.instruments:
        known = {
            r[0]
            for r in conn.execute(
                "SELECT instrument_id FROM instrument_alias WHERE source='nse' AND valid_to IS NULL"
                " AND instrument_id = ANY(%s)",
                (list(needs.instruments),),
            )
        }
        stats = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "SELECT instrument_id, count(DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date),"
                " bool_or((ts AT TIME ZONE 'Asia/Kolkata')::date = %(d)s) FROM bar_1d"
                " WHERE source=%(s)s AND instrument_id = ANY(%(ids)s)"
                " AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= %(d)s GROUP BY 1",
                {"d": needs.day, "s": bar_source, "ids": list(needs.instruments)},
            )
        }
        for iid in needs.instruments:
            n, on_day = stats.get(iid, (0, False))
            if iid not in known:
                out.unready.append(Reason("UNKNOWN_INSTRUMENT", "no current NSE symbol", iid))
            elif not on_day:
                out.unready.append(Reason("NO_BAR", f"no bar on {needs.day}", iid))
            elif n < needs.warmup_bars:
                out.unready.append(
                    Reason("SHORT_HISTORY", f"{n} bars, {needs.warmup_bars} needed", iid)
                )
        share = Decimal(len(needs.instruments) - len(out.unready)) / Decimal(len(needs.instruments))
        if share < needs.min_coverage:
            out.reasons.append(
                Reason(
                    "COVERAGE",
                    f"{len(needs.instruments) - len(out.unready)} of {len(needs.instruments)} instruments"
                    f" are ready, {needs.min_coverage:.0%} needed",
                )
            )
    return out

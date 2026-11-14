"""Daily scan of the raw NSE closes for price jumps nobody recorded (the safety net once bhavcopy is
the only price source: an action our parser could not price shows up here as a jump).

A jump (or a recorded split whose price move is missing) is
  unexplained  no corporate action of any kind, status or date touches that bar: alert
  pending      an action is recorded for that bar but waits for a person (review status) or is not a
               price factor (dividend, buy-back): shown, not alerted
Runs of closes more than MAX_GAP_DAYS apart are separate (a stock that did not trade for weeks can
legitimately reappear far away)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from algo.data.adjust.factors import PRICE_KINDS, SPLIT_KINDS, Adjustment, build_adjustments
from algo.data.corporate_actions import records_for
from algo.data.quality.continuity import Issue, continuity_issues

MAX_GAP_DAYS = 5
LOOKBACK = timedelta(
    days=10
)  # closes before `since`, so the first bar of the window has a previous one


@dataclass(frozen=True)
class Finding:
    symbol: str
    day: date
    kind: str
    detail: str


@dataclass
class ScanResult:
    scanned: int = 0
    unexplained: list[Finding] = field(default_factory=list)
    pending: list[Finding] = field(default_factory=list)


def _runs(closes: list[tuple[date, Decimal]]) -> list[list[tuple[date, Decimal]]]:
    runs: list[list[tuple[date, Decimal]]] = []
    for item in closes:
        if runs and (item[0] - runs[-1][-1][0]).days <= MAX_GAP_DAYS:
            runs[-1].append(item)
        else:
            runs.append([item])
    return runs


def scan(
    conn: psycopg.Connection,
    since: date,
    *,
    jump: Decimal = Decimal("0.20"),
    tol: Decimal = Decimal("0.25"),
) -> ScanResult:
    names: dict[int, str] = dict(
        conn.execute(
            "SELECT instrument_id, source_symbol FROM instrument_alias"
            " WHERE source='nse' AND valid_to IS NULL"
        ).fetchall()
    )
    series: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
    for iid, day, close in conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id,"
        " (ts AT TIME ZONE 'Asia/Kolkata')::date, close FROM bar_1d"
        " WHERE source='nse' AND ts >= %s::date - %s"
        " ORDER BY instrument_id, ts, dataset_version DESC",
        (since, LOOKBACK.days),
    ):
        series[iid].append((day, Decimal(close)))
    touched: dict[int, list[date]] = defaultdict(list)  # any action, any status, any kind
    for iid, ex in conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE ex_date >= %s::date - %s",
        (since, LOOKBACK.days),
    ):
        touched[iid].append(ex)
    out = ScanResult(scanned=len(series))
    for iid, closes in sorted(series.items(), key=lambda kv: names.get(kv[0], "")):
        adj: list[Adjustment] = []
        if iid in touched:
            recs = [
                r
                for r in records_for(conn, iid)
                if r.kind in (*SPLIT_KINDS, *PRICE_KINDS) and r.status == "ok"
            ]
            adj = build_adjustments(recs, lambda _d: Decimal(1)).adjustments
        issues: list[Issue] = []
        for run in _runs(closes):
            issues += continuity_issues(run, adj, jump=jump, tol=tol)
        for i in issues:
            if i.day < since:
                continue
            f = Finding(names.get(iid, str(iid)), i.day, i.kind, i.detail)
            prev = max((d for d, _ in closes if d < i.day), default=i.day)
            near = any(prev < ex <= i.day for ex in touched.get(iid, []))
            # a recorded split the price did not follow is a data error, never "pending"
            pending = near and i.kind != "action_without_discontinuity"
            (out.pending if pending else out.unexplained).append(f)
    return out

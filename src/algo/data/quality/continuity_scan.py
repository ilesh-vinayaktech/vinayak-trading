"""Daily scan of the raw NSE closes for price jumps nobody recorded (the safety net once bhavcopy is
the only price source: an action our parser could not price shows up here as a jump).

A jump (or a recorded split whose price move is missing) is
  unexplained  no corporate action of any kind, status or date touches that bar: alert
  pending      an action is recorded for that bar but waits for a person (review status) or is not a
               price factor (dividend, buy-back), or the move spans a session NSE has no bars for
               (a Muhurat or Saturday session its file does not carry, a day it did not publish):
               shown, not alerted
Runs of closes more than MAX_GAP_DAYS apart are separate (a stock that did not trade for weeks can
legitimately reappear far away)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import psycopg

from algo.data.adjust.factors import PRICE_KINDS, SPLIT_KINDS, Adjustment, build_adjustments
from algo.data.corporate_actions import records_for
from algo.data.quality.continuity import Issue, continuity_issues

MAX_GAP_DAYS = 5
RIGHTS_ENTITLEMENT = re.compile(
    r"-RE\d*$"
)  # NSE's rights-entitlement series (SUVID-RE, X-RE1): not tracked
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


def _missing_sessions(conn: psycopg.Connection, first: date) -> set[date]:
    """Days the exchange traded (a Kite bar, a calendar SESSION entry, or an open weekday) but NSE
    has no bars for at all: a move across one of them is two sessions long, not a jump."""
    last_row = conn.execute(
        "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d"
    ).fetchone()
    last = last_row[0] if last_row and last_row[0] else first

    def days(sql: str) -> set[date]:
        return {r[0] for r in conn.execute(sql, (first, last))}

    nse = days(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE source='nse'"
        " AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s"
    )
    kite = days(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE source='kite'"
        " AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s"
    )
    sessions = days(
        "SELECT session_date FROM market_session"
        " WHERE kind='SESSION' AND session_date BETWEEN %s AND %s"
    )
    closed = days(
        "SELECT session_date FROM market_session"
        " WHERE kind='CLOSED' AND session_date BETWEEN %s AND %s"
    )
    # the platform's only evidence of a holiday: NSE published no file for it
    closed |= {
        date.fromisoformat(str(r[0]))
        for r in conn.execute(
            "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status"
            " FROM partition_load ORDER BY source, dataset, partition, id DESC)"
            " SELECT partition FROM l WHERE status='not_published'"
        )
    }
    weekdays = {
        first + timedelta(days=i)
        for i in range((last - first).days + 1)
        if (first + timedelta(days=i)).weekday() < 5
    }
    return ((kite | sessions | weekdays) - closed) - nse


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
    skip = {i for i, n in names.items() if RIGHTS_ENTITLEMENT.search(n)}
    for iid, day, close in conn.execute(
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id,"
        " (ts AT TIME ZONE 'Asia/Kolkata')::date, close FROM bar_1d"
        " WHERE source='nse' AND ts >= %s::date - %s"
        " ORDER BY instrument_id, ts, dataset_version DESC",
        (since, LOOKBACK.days),
    ):
        if iid not in skip:
            series[iid].append((day, Decimal(close)))
    touched: dict[int, list[date]] = defaultdict(list)  # any action, any status, any kind
    for iid, ex in conn.execute(
        "SELECT instrument_id, ex_date FROM corporate_action WHERE ex_date >= %s::date - %s",
        (since, LOOKBACK.days),
    ):
        touched[iid].append(ex)
    missing = _missing_sessions(conn, since - LOOKBACK)
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
            if i.kind != "action_without_discontinuity" and any(prev < m < i.day for m in missing):
                f = Finding(
                    f.symbol, f.day, f.kind, f"{f.detail}; spans a session without NSE bars"
                )
                near = True
            # a recorded split the price did not follow is a data error, never "pending"
            pending = near and i.kind != "action_without_discontinuity"
            (out.pending if pending else out.unexplained).append(f)
    return out

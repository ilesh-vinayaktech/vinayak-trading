"""Completeness of the daily NSE bars (the only price series after the cutoff), three questions:
  quarantined   a file whose latest load was refused: a person must recover it (never reopened by
                itself; not limited to the window)
  missing_days  an open weekday with no NSE bars that is neither a recorded holiday (NSE published
                no file) nor a calendar CLOSED day
  thin_days     a session with fewer bars than FLOOR of the average of the sessions before it
Reads only; the scheduled check exits 1 on any of them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import psycopg

FLOOR = 0.9  # a session below 90% of the trailing average is thin
WINDOW = 20  # sessions in that average


@dataclass
class Report:
    quarantined: list[date] = field(default_factory=list)
    missing_days: list[date] = field(default_factory=list)
    thin_days: list[tuple[date, int, int]] = field(default_factory=list)  # (day, bars, average)


def check(conn: psycopg.Connection, since: date) -> Report:
    latest = conn.execute(
        "WITH l AS (SELECT DISTINCT ON (source, dataset, partition) partition, status FROM"
        " partition_load WHERE source='nse' ORDER BY source, dataset, partition, id DESC)"
        " SELECT partition, status FROM l"
    ).fetchall()
    counts: dict[date, int] = dict(
        conn.execute(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, count(*) FROM bar_1d"
            " WHERE source='nse' AND ts >= %s::date - 60 GROUP BY 1",
            (since,),
        ).fetchall()
    )
    closed = {
        r[0] for r in conn.execute("SELECT session_date FROM market_session WHERE kind='CLOSED'")
    }
    closed |= {d for d, status in latest if status == "not_published"}
    out = Report(quarantined=sorted(d for d, status in latest if status == "quarantined"))
    if not counts:
        return out
    last = max(counts)
    sessions: list[int] = []
    for i in range((last - (since - timedelta(days=60))).days + 1):
        d = since - timedelta(days=60) + timedelta(days=i)
        n = counts.get(d, 0)
        if d >= since and n:
            recent = sessions[-WINDOW:]
            if recent and n < FLOOR * (avg := round(sum(recent) / len(recent))):
                out.thin_days.append((d, n, avg))
        if n:
            sessions.append(n)
        elif d >= since and d.weekday() < 5 and d not in closed:
            out.missing_days.append(d)
    return out

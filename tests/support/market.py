"""Synthetic Kite-source daily bars for the screener tests. ENGINEERING_TEST_ONLY: nothing here is a market."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def sessions(n, start=date(2024, 1, 1)):
    """The next `n` weekdays from `start`."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def put_path(conn, iid, days, steps):
    """One bar per day from 100, moving by each `(count, step)` leg in turn (the last leg runs to the end)."""
    legs = [s for count, s in steps for _ in range(count)]
    p = D(100)
    for i, d in enumerate(days):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,1000,'kite',%s,1,%s)",
            (iid, datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC), p, p, p, p, date(2026, 11, 1), NOW),
        )  # fmt: skip
        p *= 1 + D(legs[min(i, len(legs) - 1)])


def put(conn, iid, step, days):
    put_path(conn, iid, days, [(1, step)])

# ruff: noqa: E501
"""The chart's decisions of a generated definition for one stock, kept in definition_signal_series / definition_signal_day (migration 086) so the next request computes only the new days.

Callers: algo.api.strategy_routes (definition_signals) and tests/integration/factory/test_signal_cache.py. Nothing similar exists. User's instruction: "in charts, can we store one stock calculations for
stratergies we just added into some table along with timeframe and dates and next time, it has to calculate only new".

A series starts on the first day it was asked for and runs to the last bar day computed. A request inside it is served from it; one that reaches past its last day continues from the stored state
(held or not, the rebalance period) and appends only the new days; one that starts before its first day recomputes the whole range and replaces it, because a decision depends on the path before it.
It is keyed by the definition's hash, so a definition (immutable) can never be served another's decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from algo.factory.signals import Decision

TIMEFRAME = "1D"


@dataclass(frozen=True)
class Series:
    series_id: int
    first_day: date
    last_day: date
    days: list[Decision]  # the stored decisions between the asked days, in order
    last: Decision | None  # the series' final stored decision (the state to continue from)


def get(
    conn: psycopg.Connection, sid: str, version: int, sha: str, iid: int, start: date, end: date
) -> Series | None:
    row = conn.execute(
        "SELECT series_id, first_day, last_day FROM definition_signal_series WHERE strategy_id=%s AND version=%s AND definition_sha256=%s AND instrument_id=%s AND timeframe=%s",
        (sid, version, sha, iid, TIMEFRAME),
    ).fetchone()
    if row is None:
        return None
    rows = conn.execute(
        "SELECT day, ready, action, reason, holding_after FROM definition_signal_day WHERE series_id=%s AND day BETWEEN %s AND %s ORDER BY day",
        (row[0], start, end),
    ).fetchall()
    final = conn.execute(
        "SELECT day, ready, action, reason, holding_after FROM definition_signal_day WHERE series_id=%s ORDER BY day DESC LIMIT 1",
        (row[0],),
    ).fetchone()
    return Series(
        row[0], row[1], row[2], [Decision(*r) for r in rows], Decision(*final) if final else None
    )


def save(
    conn: psycopg.Connection,
    sid: str,
    version: int,
    sha: str,
    iid: int,
    decisions: list[Decision],
    now: datetime,
    *,
    replace: bool,
) -> None:
    """Append `decisions` (consecutive days after the stored last day) to the series, or with `replace` make them the whole series."""
    if not decisions:
        return
    row = conn.execute(
        "SELECT series_id FROM definition_signal_series WHERE strategy_id=%s AND version=%s AND definition_sha256=%s AND instrument_id=%s AND timeframe=%s",
        (sid, version, sha, iid, TIMEFRAME),
    ).fetchone()
    first, last = decisions[0].day, decisions[-1].day
    if row is None:
        row = conn.execute(
            "INSERT INTO definition_signal_series (strategy_id, version, definition_sha256, instrument_id, timeframe, first_day, last_day, computed_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING series_id",
            (sid, version, sha, iid, TIMEFRAME, first, last, now, now),
        ).fetchone()
    elif replace:
        conn.execute("DELETE FROM definition_signal_day WHERE series_id=%s", (row[0],))
        conn.execute(
            "UPDATE definition_signal_series SET first_day=%s, last_day=%s, computed_at=%s, updated_at=%s WHERE series_id=%s",
            (first, last, now, now, row[0]),
        )
    else:
        conn.execute(
            "UPDATE definition_signal_series SET last_day=%s, updated_at=%s WHERE series_id=%s",
            (last, now, row[0]),
        )
    assert row is not None
    conn.cursor().executemany(
        "INSERT INTO definition_signal_day (series_id, day, ready, action, reason, holding_after) VALUES (%s,%s,%s,%s,%s,%s)",
        [(row[0], d.day, d.ready, d.action, d.reason, d.holding_after) for d in decisions],
    )

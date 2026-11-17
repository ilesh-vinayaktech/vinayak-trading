# ruff: noqa: E501
"""Heartbeats for the long-running processes and the alert when one goes quiet (docs: TODO 5.3).

A process calls `beat` every few seconds. `assess` (pure) turns the latest beats into problems: a process that never reported, one that
is silent for longer than its limit, one that says it is DEGRADED, or one that says it STOPPED while it should be running. The live feed
is not asked to change: its own `feed_status` row is read as its heartbeat (`from_feed_status`). Which processes are expected is set by
`ALGO_EXPECT_PROCESSES` (default: the feed only), so a machine that does not run the study worker is not alerted about it.
Redis is not used and not needed: the table is the source of truth, and a missed heartbeat is just a row that stopped changing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg

from algo.live import market_calendar


@dataclass(frozen=True)
class Beat:
    process: str
    state: str  # STARTING | RUNNING | DEGRADED | STOPPED
    detail: str
    beat_at: datetime


@dataclass(frozen=True)
class Expectation:
    process: str
    max_silence: timedelta
    session_only: (
        bool  # expected only while the market is open (the feed ends with the session on purpose)
    )


CLOCK_TOLERANCE_S = 60.0  # a beat from the future by more than this means the clocks disagree

DEFAULT_EXPECTED = {
    "feed": Expectation("feed", timedelta(seconds=120), session_only=True),
    "study_worker": Expectation("study_worker", timedelta(seconds=300), session_only=False),
    "live": Expectation("live", timedelta(seconds=120), session_only=True),
}

_FEED_STATE = {
    "STARTING": "STARTING",
    "CONNECTED": "RUNNING",
    "RECONNECTING": "DEGRADED",
    "TOKEN_EXPIRED": "DEGRADED",
    "STOPPED": "STOPPED",
}


def from_feed_status(row: Mapping[str, Any] | None) -> Beat | None:
    """The live feed's own status row, seen as a heartbeat."""
    if row is None:
        return None
    return Beat("feed", _FEED_STATE.get(row["state"], "DEGRADED"), row["detail"], row["updated_at"])


def expected_from_env(env: Mapping[str, str]) -> list[Expectation]:
    names = [n.strip() for n in env.get("ALGO_EXPECT_PROCESSES", "feed").split(",") if n.strip()]
    for n in names:
        if n not in DEFAULT_EXPECTED:
            raise ValueError(
                f"unknown process {n!r} in ALGO_EXPECT_PROCESSES (known: {', '.join(DEFAULT_EXPECTED)})"
            )
    return [DEFAULT_EXPECTED[n] for n in names]


def assess(
    beats: Mapping[str, Beat], expected: Sequence[Expectation], now: datetime, *, in_session: bool
) -> list[str]:
    problems: list[str] = []
    for e in expected:
        if e.session_only and not in_session:
            continue
        b = beats.get(e.process)
        if b is None:
            problems.append(f"{e.process} has never reported")
            continue
        silent = (now - b.beat_at).total_seconds()
        if silent < -CLOCK_TOLERANCE_S:
            problems.append(
                f"{e.process}'s heartbeat is {-silent:.0f} s ahead of this clock: clock skew, so silence cannot be judged"
            )
        elif b.state == "STOPPED":
            problems.append(
                f"{e.process} is STOPPED (last beat {silent:.0f} s ago) but should be running"
            )
        elif silent > e.max_silence.total_seconds():
            problems.append(
                f"{e.process} has been silent for {silent:.0f} s (limit {e.max_silence.total_seconds():.0f} s), last state {b.state}"
            )
        elif b.state == "DEGRADED":
            problems.append(f"{e.process} is DEGRADED: {b.detail or 'no detail'}")
    return problems


def beat(
    conn: psycopg.Connection,
    process: str,
    state: str,
    detail: str,
    now: datetime,
    *,
    pid: int,
    host: str,
) -> None:
    """Write this process's heartbeat. `started_at` is set when it first appears and again whenever the state returns to STARTING."""
    conn.execute(
        "INSERT INTO process_heartbeat (process, pid, host, state, detail, started_at, beat_at) VALUES (%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (process) DO UPDATE SET pid=EXCLUDED.pid, host=EXCLUDED.host, state=EXCLUDED.state, detail=EXCLUDED.detail,"
        " beat_at=EXCLUDED.beat_at, started_at=CASE WHEN EXCLUDED.state='STARTING' THEN EXCLUDED.started_at ELSE process_heartbeat.started_at END",
        (process, pid, host, state, detail, now, now),
    )


def load(conn: psycopg.Connection) -> dict[str, Beat]:
    beats = {
        r[0]: Beat(r[0], r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT process, state, detail, beat_at FROM process_heartbeat"
        ).fetchall()
    }
    feed = conn.execute("SELECT state, detail, updated_at FROM feed_status").fetchone()
    fb = from_feed_status(
        None if feed is None else {"state": feed[0], "detail": feed[1], "updated_at": feed[2]}
    )
    if fb is not None:
        beats["feed"] = fb
    return beats


def in_session(conn: psycopg.Connection, now: datetime) -> bool:
    day = now.astimezone(market_calendar.IST).date()
    return any(start <= now < end for start, end in market_calendar.windows_for(conn, day))


def check(conn: psycopg.Connection, now: datetime, expected: Sequence[Expectation]) -> list[str]:
    return assess(load(conn), expected, now, in_session=in_session(conn, now))

# ruff: noqa: E501
"""The research slot (docs/vti-phase1-spec.md item G): ONE PostgreSQL advisory lock that every research entry point holds while it works, so two
heavy jobs (a study run, the holdout evaluation, the feature job, a research backtest) never compete for the machine's memory and cores.

A lock only serialises, it does not yield: long jobs also checkpoint (the feature job does) and ask `busy_reason` before each unit, which says a
paper run, paper orders or the market-hours window needs the machine. `hold` waits (polling) up to `timeout_s`; the lock belongs to the connection,
so a dead process frees it by itself."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

import psycopg

KEY = (8302, 1)  # (class, object): study_jobs uses class 8301 for its per-run locks
IST = ZoneInfo("Asia/Kolkata")
MARKET = (dtime(9, 0), dtime(15, 45))  # the live feed and paper orders run in this window
YIELD_TO = ("run_paper.py", "paper_orders.py")  # processes that outrank research
_held: set[int] = (
    set()
)  # connections of this process that hold the slot (a second take on one of them would silently nest)


class SlotTimeout(Exception):
    pass


def holder(conn: psycopg.Connection) -> str:
    row = conn.execute(
        "SELECT a.application_name, a.pid FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE l.locktype='advisory' AND l.classid=%s AND l.objid=%s AND l.granted LIMIT 1",
        KEY,
    ).fetchone()
    return f"{row[0] or 'a process'} (pid {row[1]})" if row else "someone"


@contextmanager
def hold(
    conn: psycopg.Connection,
    who: str,
    *,
    timeout_s: float | None = None,
    poll_s: float = 1.0,
    nice: int = 0,
    slots: int = 1,
) -> Iterator[None]:
    """Wait for the slot, hold it for the body, release it. `who` is for the message of whoever times out behind us (and sets the connection's
    application_name while held). `nice` > 0 lowers this process's CPU priority for the rest of its life. `slots` > 1 lets that many holders work at once
    (study runs only; each is about 2 GB, so it is the machine's memory that sets it); every other job asks for one, and so still waits for the first."""
    if id(conn) in _held:
        raise SlotTimeout(f"{who}: this connection already holds the research slot")
    if conn.autocommit is False:
        raise ValueError(
            "the research slot needs an autocommit connection (its lock must not wait for a transaction)"
        )
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    got: tuple[int, int] | None = None
    while got is None:
        for i in range(slots):
            k = (KEY[0], KEY[1] + i)
            if conn.execute("SELECT pg_try_advisory_lock(%s, %s)", k).fetchone()[0]:  # type: ignore[index]
                got = k
                break
        else:
            if deadline is not None and time.monotonic() >= deadline:
                raise SlotTimeout(
                    f"{who}: the research slot is held by {holder(conn)}; gave up after {timeout_s}s"
                )
            time.sleep(poll_s)
    _held.add(id(conn))
    conn.execute("SELECT set_config('application_name', %s, false)", (f"research:{who}",))
    if nice:
        os.nice(nice)
    try:
        yield
    finally:
        _held.discard(id(conn))
        conn.execute("SELECT pg_advisory_unlock(%s, %s)", got)


def busy_reason(now: datetime, commandlines: Iterable[str]) -> str | None:
    """Why the machine belongs to something else right now, or None."""
    for line in commandlines:
        for name in YIELD_TO:
            if name in line:
                return f"{name} is running"
    local = now.astimezone(IST)
    if local.weekday() < 5 and MARKET[0] <= local.time() <= MARKET[1]:
        return "market hours"
    return None

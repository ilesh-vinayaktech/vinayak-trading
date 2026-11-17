# ruff: noqa: E501
"""Holdout policy v3 section 7: `strategy_locked_at` and `forward_evaluation_start` per candidate.

`strategy_locked_at` is the LATEST of every lock that can affect a decision: (a) the definition (insert-only, hashed), (b) the settings it trades at and (c) the universe, costs and risk
settings, all fixed when its fixed-setting study was registered and locked in `study_sha256`, and (d) the code that turns them into decisions, pinned by the study's commit (the commit's
own time). The paper runner's code is not pinned by the study; that is recorded as an open item in each row, not hidden. `forward_evaluation_start` is the first trading session that OPENS after
that moment and after 2026-11-13: a candidate locked on 1 December cannot count 14-30 November."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from algo.live.market_calendar import windows_for
from algo.research.holdout_cutoff import _fixed_study

HOLDOUT_END = date(2026, 11, 13)
ROOT = "."


class LockError(ValueError):
    pass


def commit_time(commit: str, run: Callable[..., Any] = subprocess.run) -> datetime | None:
    """The committer time of a commit, or None when git cannot say (then the lock is refused, never guessed)."""
    out = run(
        ["git", "show", "-s", "--format=%cI", commit],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return datetime.fromisoformat(out.stdout.strip()).astimezone(UTC)


def first_session_after(
    conn: psycopg.Connection, moment: datetime, floor: date = HOLDOUT_END
) -> date:
    """The first trading session that opens after `moment` and falls after `floor`."""
    day = max(moment.date(), floor) - timedelta(days=1)
    for _ in range(40):
        day += timedelta(days=1)
        if day <= floor:
            continue
        if any(start > moment for start, _ in windows_for(conn, day)):
            return day
    raise LockError(f"no trading session found within 40 days after {moment}")


def compute(
    conn: psycopg.Connection,
    candidate_id: str,
    commit_time_of: Callable[[str], datetime | None] = commit_time,
) -> dict[str, Any]:
    sid, ver = candidate_id.split("@")
    d = conn.execute(
        "SELECT created_at, definition_sha256 FROM strategy_definition WHERE strategy_id=%s AND version=%s",
        (sid, int(ver)),
    ).fetchone()
    exp = _fixed_study(conn, sid, int(ver))
    if d is None or exp is None:
        raise LockError(f"{candidate_id}: no definition or no fixed-setting study yet")
    row = conn.execute(
        "SELECT registered_at, study FROM experiment WHERE experiment_id=%s", (exp,)
    ).fetchone()
    assert row is not None
    reg, study = row
    code = (study or {}).get("code") or {}
    commit = code.get("commit")
    if not commit or code.get("dirty", True):
        raise LockError(
            f"{candidate_id}: its study was registered from source that differs from its commit, so the code lock is unknown"
        )
    ct = commit_time_of(commit)
    if ct is None:
        raise LockError(f"{candidate_id}: the time of commit {commit} cannot be established")
    parts = {
        "definition": d[0],
        "settings_universe_costs_risk (study registration)": reg,
        f"code commit {commit[:10]}": ct,
    }
    locked = max(parts.values())
    return {
        "candidate_id": candidate_id, "strategy_locked_at": locked, "forward_evaluation_start": first_session_after(conn, locked),
        "definition_sha256": d[1], "code_commit": commit,
        "components": {**{k: v.isoformat() for k, v in parts.items()}, "experiment_id": exp, "not_pinned": ["paper runner code (a difference in it is a deviation under D3 item 6)"]},
    }  # fmt: skip


def record(conn: psycopg.Connection, rec: dict[str, Any], now: datetime) -> None:
    conn.execute(
        "INSERT INTO strategy_lock (candidate_id, strategy_locked_at, forward_evaluation_start, definition_sha256, code_commit, components, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            rec["candidate_id"],
            rec["strategy_locked_at"],
            rec["forward_evaluation_start"],
            rec["definition_sha256"],
            rec["code_commit"],
            Jsonb(rec["components"]),
            now,
        ),
    )


def compute_all(
    conn: psycopg.Connection, commit_time_of: Callable[[str], datetime | None] = commit_time
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every definition's lock, and the reasons for those that cannot be computed."""
    ok, refused = [], {}
    for sid, ver in conn.execute(
        "SELECT strategy_id, version FROM strategy_definition ORDER BY 1, 2"
    ).fetchall():
        try:
            ok.append(compute(conn, f"{sid}@{ver}", commit_time_of))
        except LockError as e:
            refused[f"{sid}@{ver}"] = str(e)
    return ok, refused

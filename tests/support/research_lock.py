"""Test helpers for the research holdout lock: an open lock far in the future (so ordinary study tests are unaffected) and a way to anchor it."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from algo.research import holdout_lock

OPEN = holdout_lock.Lock(date(2099, 12, 30), date(2099, 12, 31), date(2099, 12, 31))


def write_lock_file(path: Path, lock: holdout_lock.Lock = OPEN) -> Path:
    path.write_text(
        json.dumps(
            {
                k: getattr(lock, k).isoformat()
                for k in ("development_end", "holdout_start", "holdout_end")
            }
        )
    )
    return path


def anchor_open_lock(conn, lock: holdout_lock.Lock = OPEN) -> None:
    holdout_lock.anchor(
        conn, lock, by="test", reason="test fixture", now=datetime(2026, 11, 14, tzinfo=UTC)
    )

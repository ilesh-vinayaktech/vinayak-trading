from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest

from algo.data.store.migrate import migrate
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock, LockMismatch
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 14, tzinfo=UTC)
REAL = Lock(date(2024, 12, 31), date(2025, 1, 1), date(2026, 11, 13))


def test_the_committed_lock_file_is_the_agreed_window():
    # the autouse fixture points LOCK_FILE at an open test window, so read the file in the repository directly
    shipped = Path(holdout_lock.__file__).resolve().parents[3] / "config" / "research_holdout.json"
    assert (
        holdout_lock.from_file(shipped) == REAL
    )  # development to 2024-12-31, holdout 2025-01-01 to 2026-11-13


def test_nothing_anchored_means_every_research_reader_is_refused(conn, tmp_path):
    migrate(conn)
    with pytest.raises(LockMismatch, match="not anchored"):
        holdout_lock.require(conn, write_lock_file(tmp_path / "l.json", REAL))


def test_the_file_must_match_the_newest_anchored_row_or_research_fails_closed(conn, tmp_path):
    migrate(conn)
    f = write_lock_file(tmp_path / "l.json", REAL)
    holdout_lock.anchor(conn, REAL, by="owner", reason="first lock", now=NOW)
    assert holdout_lock.require(conn, f) == REAL
    wider = Lock(
        date(2025, 6, 30), date(2025, 7, 1), date(2026, 11, 13)
    )  # someone edits the file to open the holdout
    write_lock_file(f, wider)
    with pytest.raises(LockMismatch, match="differs"):
        holdout_lock.require(conn, f)
    holdout_lock.anchor(
        conn, wider, by="owner", reason="deliberate change", now=NOW
    )  # a deliberate, recorded change
    assert holdout_lock.require(conn, f) == wider


def test_anchored_rows_cannot_be_changed_or_deleted(conn):
    migrate(conn)
    holdout_lock.anchor(conn, REAL, by="owner", reason="first lock", now=NOW)
    for sql in ("UPDATE research_lock SET set_by='x'", "DELETE FROM research_lock"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(sql)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO research_lock (config_sha256, development_end, holdout_start, holdout_end, set_by, reason, set_at)"
            " VALUES ('h','2025-01-01','2025-01-01','2026-01-01','o','r', now())"
        )


def test_without_an_anchored_lock_no_study_can_be_registered(conn):
    from algo.research.study_store import register_study
    from tests.unit.research.test_study import spec

    migrate(conn)
    with pytest.raises(LockMismatch):
        register_study(
            conn, None, spec(), NOW
        )  # refused before the owner or the data are even looked at

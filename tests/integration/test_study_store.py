"""Registering a backtest study: it pins the frozen data and the cost schedules, and from then on it cannot change."""

from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest

from algo.backtest.costs import schedule_store
from algo.backtest.validation import registry
from algo.core.clock import SimClock
from algo.data import freeze
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.research.study import StudyError
from algo.research.study_store import get_study, list_studies, register_study
from tests.support.portal import add_user
from tests.unit.research.test_study import spec

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    conn.execute(
        "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,adjusted_through,dataset_version,ingested_at)"
        " VALUES (%s,'2026-11-11 03:45+00',1,1,1,1,1,'kite','2026-11-11',1,%s)",
        (iid, NOW),
    )
    fid = freeze.take(conn, "kite", date(2026, 11, 11), NOW, "reference history")
    schedule_store.import_files(conn, Path("config/cost_schedules"), now=NOW)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    return conn, owner, fid


def test_a_registered_study_records_its_settings_trials_frozen_data_and_cost_schedules(env):
    conn, owner, fid = env
    sid = register_study(conn, owner, spec(), NOW)
    s = get_study(conn, sid)
    assert (s["name"], s["strategy_id"], s["trials_planned"], s["trials_run"], s["holdout_opened_at"]) == (
        "Pullback, large and mid caps", "trend_pullback", 12, 0, None,
    )  # fmt: skip
    assert (
        s["spec"]["universe"]["segments"] == ["large", "mid"] and s["spec"]["capital"] == "1000000"
    )
    assert s["data_freeze"] == {"id": str(fid), "through": "2026-11-11"}
    assert s["cost_schedules"] and all(c["broker"] == "zerodha" for c in s["cost_schedules"])
    assert len(s["combinations"]) == 12 and len(s["sha256"]) == 64 and s["owner_user_id"] == owner
    row = conn.execute(
        "SELECT param_ranges, holdout_start, holdout_end FROM experiment WHERE experiment_id=%s",
        (sid,),
    ).fetchone()
    assert row == ({"entry_rsi": [20, 30], "exit_rsi": [60, 65], "max_positions": [10, 10], "trend_sma": [100, 200]},
                   date(2024, 5, 1), date(2026, 11, 6))  # fmt: skip
    assert [x["experiment_id"] for x in list_studies(conn)] == [sid]


def test_a_registered_study_is_locked_and_its_holdout_can_be_stamped_only_once(env):
    conn, owner, _ = env
    sid = register_study(conn, owner, spec(), NOW)
    for change in (
        "name='other'",
        "hypothesis='a different idea entirely'",
        "holdout_start='2025-01-01'",
        "study='{}'::jsonb",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="locked"):
            conn.execute(f"UPDATE experiment SET {change} WHERE experiment_id=%s", (sid,))
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be deleted"):
        conn.execute("DELETE FROM experiment WHERE experiment_id=%s", (sid,))
    conn.execute(
        "UPDATE experiment SET holdout_opened_at=%s WHERE experiment_id=%s", (NOW, sid)
    )  # the one allowed change
    with pytest.raises(psycopg.errors.RaiseException, match="already opened"):
        conn.execute(
            "UPDATE experiment SET holdout_opened_at=%s WHERE experiment_id=%s",
            (datetime(2027, 1, 1, tzinfo=UTC), sid),
        )


def test_a_study_must_end_inside_the_frozen_history_have_costs_and_a_unique_name(env):
    conn, owner, _ = env
    with pytest.raises(StudyError, match="frozen history"):
        register_study(
            conn,
            owner,
            spec(end="2026-11-12", holdout_start="2024-05-01"),
            datetime(2026, 11, 13, 6, tzinfo=UTC),
        )
    with pytest.raises(StudyError, match="no cost schedule"):
        register_study(conn, owner, spec(broker="nobody"), NOW)
    register_study(conn, owner, spec(), NOW)
    with pytest.raises(StudyError, match="already a study"):
        register_study(conn, owner, spec(), NOW)
    with pytest.raises(StudyError, match="survivorship"):
        register_study(conn, owner, spec(start="2016-01-01", name="early"), NOW)


def test_without_a_frozen_history_nothing_can_be_registered(conn):
    migrate(conn)
    owner = add_user(conn, SimClock(NOW), "TRADER", "jane@example.com")
    with pytest.raises(StudyError, match="freeze"):
        register_study(conn, owner, spec(), NOW)
    assert get_study(conn, 999) is None and list_studies(conn) == []


def test_an_old_style_registration_still_works_without_study_settings(env):
    conn, _, _ = env
    eid = registry.register(
        conn, name="engine check", strategy_id="x", hypothesis="h", style="long_only",
        param_ranges={"a": [1, 2]}, holdout=(date(2025, 1, 1), date(2025, 12, 31)), now=NOW,
    )  # fmt: skip
    assert list_studies(conn) == [] and get_study(conn, eid) is None  # only studies are listed

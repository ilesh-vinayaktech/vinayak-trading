"""Provider corrections must not silently change an old result: a run pinned to a moment in time reads the data as the
database held it then, whatever has been ingested since."""

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.backtest.engine import run_backtest
from algo.backtest.store import save_run
from algo.data.reader import BarReader
from algo.data.snapshot import snapshot_hash
from tests.support.bt import DAYS, INGESTED, NOW, add_action, cfg, flat, hold, make_env, put_bars

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)  # after the first load
T1 = datetime(2026, 11, 8, 12, tzinfo=UTC)  # the provider's correction is ingested
T2 = datetime(2026, 11, 9, 12, tzinfo=UTC)  # a later moment, after the correction


@pytest.fixture
def env(conn):
    conn, a, b = make_env(conn)
    put_bars(conn, a, flat(100))
    put_bars(conn, b, flat(50))
    return conn, a, b


def correct(conn, iid, price, at=T1, version=2):
    """The provider re-issues every day of the history at a different price: a new dataset version, ingested later."""
    for d in DAYS:
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,ingested_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,10000000,'nse',%s,%s)",
            (
                iid,
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                price,
                price,
                price,
                price,
                version,
                at,
            ),
        )


def run(conn, a, known_at):
    return run_backtest(conn, hold((a, 1)), cfg(), reader=BarReader(conn, known_at=known_at))


def test_a_rerun_pinned_to_the_same_moment_is_byte_identical_after_the_provider_corrects_history(
    env,
):
    conn, a, _ = env
    before = run(conn, a, T0)
    correct(conn, a, 110)
    again = run(conn, a, T0)
    assert again.result_hash == before.result_hash and again.trades[0].price == D(100)
    assert again.snapshot == before.snapshot and before.snapshot["hash"] == snapshot_hash(
        conn, "nse", [a], T0
    )


def test_a_new_moment_or_the_latest_data_gives_a_different_result_and_snapshot(env):
    conn, a, _ = env
    before = run(conn, a, T0)
    correct(conn, a, 110)
    after, latest = run(conn, a, T2), run(conn, a, None)
    assert after.trades[0].price == D(110) and after.result_hash != before.result_hash
    assert after.snapshot["hash"] != before.snapshot["hash"]
    assert (
        latest.result_hash == after.result_hash and latest.snapshot is None
    )  # unpinned: no claim of a snapshot


def test_the_snapshot_is_recorded_with_the_saved_run(env):
    conn, a, _ = env
    r = run(conn, a, T0)
    run_id = save_run(conn, r, NOW)
    cfg_json = conn.execute(
        "SELECT config FROM backtest_run WHERE run_id=%s", (run_id,)
    ).fetchone()[0]
    assert cfg_json["data_snapshot"] == {"known_at": T0.isoformat(), "hash": r.snapshot["hash"]}


def test_the_hash_is_stable_and_changes_with_any_pinned_input(env):
    conn, a, b = env
    base = snapshot_hash(conn, "nse", [a], T0)
    assert snapshot_hash(conn, "nse", [a], T0) == base  # deterministic
    assert snapshot_hash(conn, "nse", [a, b], T0) != base  # another instrument is another input
    assert snapshot_hash(conn, "nse", [b, a], T0) == snapshot_hash(
        conn, "nse", [a, b], T0
    )  # order does not matter
    correct(conn, a, 110)
    assert snapshot_hash(conn, "nse", [a], T0) == base  # ingested after the pin: not part of it
    assert snapshot_hash(conn, "nse", [a], T2) != base  # but part of a later one
    later = snapshot_hash(conn, "nse", [a], T2)
    add_action(conn, a, DAYS[4], "bonus", num=D(2), den=D(1), ingested=T1)
    assert snapshot_hash(conn, "nse", [a], T2) != later  # a corporate action is an input too
    assert (
        snapshot_hash(conn, "nse", [a], T0) == base
    )  # but only for pins at or after its ingestion


def test_a_corporate_action_ingested_after_the_pin_does_not_change_the_pinned_run(env):
    conn, a, _ = env
    before = run(conn, a, INGESTED)  # pinned to the moment the bars were loaded, before any action
    add_action(conn, a, DAYS[4], "bonus", num=D(2), den=D(1), ingested=T1)  # known later
    again = run(conn, a, INGESTED)
    assert again.result_hash == before.result_hash and again.snapshot == before.snapshot

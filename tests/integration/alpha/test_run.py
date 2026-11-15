# ruff: noqa: E501
"""Alpha discovery on a stored market: materialised features and development-window prices in, hypotheses out.
ENGINEERING_TEST_ONLY: synthetic random-walk prices, so the right answer is 'no real signal'."""

import random
from datetime import UTC, date, datetime

import pytest

from algo.alpha import run
from algo.data import freeze as freeze_mod
from algo.data.readiness import Readiness
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.features import job, store
from algo.research import holdout_lock
from tests.integration.features.test_store import LOCK, NOW, sessions
from tests.support.bt import put_bars
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
JAN = date(2026, 1, 1)
USABLE = ("ret_5d", "ret_20d")


@pytest.fixture
def world(conn, monkeypatch, tmp_path):
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    rng = random.Random(11)
    ids = [repo.add_instrument(x, f"S{k:02d}") for k in range(8)]
    days = sessions()
    for iid in ids:
        price, series = 100.0, {}
        for d in days:
            price *= 1 + rng.gauss(0, 0.01)
            series[d] = round(price, 4)
        put_bars(conn, iid, series)
    store.register_all(conn, NOW)
    for n in USABLE:
        store.set_status(conn, n, "1", "USABLE", by="owner", reason="test", now=NOW)
    fid = freeze_mod.take(conn, "nse", days[-1], datetime(2026, 11, 7, tzinfo=UTC), "test freeze")
    job.run(
        conn, fid, JAN, NOW, "abc", ready=lambda c, n: Readiness()
    )  # materialise the usable features for the development months
    return conn, ids, fid


def test_every_usable_feature_at_every_horizon_becomes_a_recorded_hypothesis_with_the_datasets_hash(
    world,
):
    conn, ids, fid = world
    got = run.run_discovery(
        conn, fid, JAN, NOW, horizons=(1, 3), min_names=5, context={"universe": "test"}
    )
    assert len(got) == 4
    rows = conn.execute(
        "SELECT feature_name, horizon_days, dataset_sha256, research_status, evidence->'context' FROM alpha_hypothesis ORDER BY hypothesis_id"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [
        ("ret_20d", 1),
        ("ret_20d", 3),
        ("ret_5d", 1),
        ("ret_5d", 3),
    ]
    assert {r[2] for r in rows} == {job.dataset_sha256(conn, fid, ids)} and {
        r[4]["universe"] for r in rows
    } == {"test"}
    assert {r[3] for r in rows} == {
        "REJECTED"
    }  # a random walk has nothing to find, and the registry says so instead of promising something


def test_changing_any_stored_price_even_inside_the_holdout_changes_the_datasets_identity_and_the_stored_features_are_refused(
    world,
):
    """The dataset hash covers every bar of the freeze, so a quietly altered price cannot be mistaken for the data the features were computed from.
    (That a holdout price cannot move a RESULT is proved on the pure engine in tests/unit/alpha/test_discover.py.)"""
    conn, ids, fid = world
    run.measure(conn, fid, JAN, horizons=(1, 3), min_names=5)  # fine on the data as frozen
    conn.execute(
        "UPDATE bar_1d SET close = close * 3 WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date >= %s",
        (LOCK.holdout_start,),
    )
    with pytest.raises(store.FeatureError, match="no completed run"):
        run.measure(conn, fid, JAN, horizons=(1, 3), min_names=5)


def test_an_unknown_freeze_is_refused(world):
    from uuid import uuid4

    conn, _, _ = world
    with pytest.raises(run.DiscoveryError, match="no such freeze"):
        run.measure(conn, uuid4(), JAN, horizons=(1,), min_names=5)


def test_without_a_usable_feature_or_a_whole_development_month_there_is_nothing_to_discover(world):
    conn, _, fid = world
    with pytest.raises(run.DiscoveryError, match="no whole development month"):
        run.run_discovery(
            conn, fid, date(2026, 3, 1), NOW, horizons=(1,), min_names=5
        )  # the first month is already the holdout
    for n in USABLE:
        store.set_status(conn, n, "1", "BLOCKED", by="owner", reason="inputs wrong", now=NOW)
    with pytest.raises(run.DiscoveryError, match="no USABLE feature"):
        run.run_discovery(conn, fid, JAN, NOW, horizons=(1,), min_names=5)
    assert conn.execute("SELECT count(*) FROM alpha_hypothesis").fetchone() == (0,)

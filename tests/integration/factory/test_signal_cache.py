# ruff: noqa: E501
"""The stored decisions of a definition for one stock: a series that grows forward, is replaced when asked from an earlier day, and is keyed by the definition's hash."""

from datetime import UTC, date, datetime, timedelta

import pytest

from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.factory import generate, signal_cache
from algo.factory.signals import Decision

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
DEFN = generate.definition_for(
    generate.Hypothesis(1, 1, "ret_20d", "1", 1, "POSITIVE", 0.05, 0.001)
)
D0 = date(2024, 3, 4)


def run(n, first=0, buy_at=None):
    return [
        Decision(
            D0 + timedelta(days=first + i),
            True,
            "BUY" if i == buy_at else None,
            "the entry rule holds" if i == buy_at else None,
            buy_at is not None and i >= buy_at,
        )
        for i in range(n)
    ]


@pytest.fixture
def iid(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    return repo.add_instrument(repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE"), "AAA")


def test_nothing_is_stored_until_a_series_is_saved_and_a_saved_one_serves_any_range_inside_it(
    conn, iid
):
    assert signal_cache.get(conn, "S", 1, DEFN.sha256, iid, D0, D0) is None
    signal_cache.save(conn, "S", 1, DEFN.sha256, iid, run(5, buy_at=1), NOW, replace=False)
    got = signal_cache.get(
        conn, "S", 1, DEFN.sha256, iid, D0 + timedelta(days=1), D0 + timedelta(days=3)
    )
    assert (got.first_day, got.last_day) == (D0, D0 + timedelta(days=4))
    assert [(d.day, d.action) for d in got.days] == [
        (D0 + timedelta(days=1), "BUY"),
        (D0 + timedelta(days=2), None),
        (D0 + timedelta(days=3), None),
    ]
    assert got.last.holding_after is True  # the state to continue from


def test_new_days_are_appended_to_the_series_and_only_those(conn, iid):
    signal_cache.save(conn, "S", 1, DEFN.sha256, iid, run(5, buy_at=1), NOW, replace=False)
    signal_cache.save(conn, "S", 1, DEFN.sha256, iid, run(3, first=5), NOW, replace=False)
    got = signal_cache.get(conn, "S", 1, DEFN.sha256, iid, D0, D0 + timedelta(days=9))
    assert got.last_day == D0 + timedelta(days=7) and len(got.days) == 8
    assert conn.execute("SELECT count(*) FROM definition_signal_day").fetchone() == (8,)


def test_a_replace_swaps_the_whole_series_and_a_different_definition_hash_is_a_different_series(
    conn, iid
):
    signal_cache.save(conn, "S", 1, DEFN.sha256, iid, run(5), NOW, replace=False)
    signal_cache.save(conn, "S", 1, DEFN.sha256, iid, run(8, first=-3), NOW, replace=True)
    got = signal_cache.get(
        conn, "S", 1, DEFN.sha256, iid, D0 - timedelta(days=9), D0 + timedelta(days=9)
    )
    assert (got.first_day, got.last_day, len(got.days)) == (
        D0 - timedelta(days=3),
        D0 + timedelta(days=4),
        8,
    )
    assert signal_cache.get(conn, "S", 1, "f" * 64, iid, D0, D0) is None
    signal_cache.save(
        conn, "S", 1, "f" * 64, iid, [], NOW, replace=False
    )  # nothing to save: nothing created
    assert conn.execute("SELECT count(*) FROM definition_signal_series").fetchone() == (1,)

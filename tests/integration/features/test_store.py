# ruff: noqa: E501
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import psycopg
import pytest

from algo.data.reader import BarReader
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.features import registry, store
from algo.features._shared import SessionBar, q
from algo.research import holdout_lock
from algo.research.holdout_lock import Lock
from tests.support.bt import put_bars
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
DS = "a" * 64
OTHER = "b" * 64
JAN = date(2026, 1, 1)
LOCK = Lock(date(2026, 2, 28), date(2026, 3, 1), date(2026, 3, 31))


@pytest.fixture
def env(conn, monkeypatch, tmp_path):
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, s) for s in ("AAA", "BBB")]
    return conn, ids


def sessions(start=date(2025, 12, 1), n=70):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars_for(days, base):
    return {
        d: SessionBar(
            d,
            D(base + i + 1),
            D(base + i - 1),
            D(base + i),
            D(base + i),
            D(1000),
            datetime(d.year, d.month, d.day, 13, tzinfo=UTC),
        )
        for i, d in enumerate(days)
    }


def history(ids):
    days = sessions()
    return {ids[0]: bars_for(days, 100), ids[1]: bars_for(days, 200)}


def test_registering_stores_every_definition_as_a_draft_and_a_changed_one_is_refused_before_anything_is_written(
    env, monkeypatch
):
    conn, _ = env
    assert store.register_all(conn, NOW) == 19 and store.register_all(conn, NOW) == 0  # idempotent
    assert {store.status(conn, n, "1") for n in registry.DEFINITIONS} == {"DRAFT"}
    f = registry.DEFINITIONS["ret_5d"]
    import dataclasses

    monkeypatch.setitem(
        registry.DEFINITIONS,
        "ret_5d",
        dataclasses.replace(
            f, manifest={**f.manifest, "definition": "edited without a new version"}
        ),
    )
    with pytest.raises(store.FeatureError, match=r"ret_5d@1"):
        store.register_all(conn, NOW)


def test_status_moves_only_by_new_rows_and_only_usable_features_can_be_named(env):
    conn, _ = env
    store.register_all(conn, NOW)
    with pytest.raises(store.FeatureError, match="ret_5d@1 \\(DRAFT\\)"):
        store.require_usable(conn, [("ret_5d", "1")])
    store.set_status(
        conn, "ret_5d", "1", "USABLE", by="owner", reason="validated 2026-11-15", now=NOW
    )
    store.require_usable(conn, [("ret_5d", "1")])
    store.set_status(conn, "ret_5d", "1", "BLOCKED", by="owner", reason="input problem", now=NOW)
    assert conn.execute(
        "SELECT count(*) FROM feature_status s JOIN feature_definition d USING (feature_id) WHERE d.name='ret_5d'"
    ).fetchone() == (3,)  # DRAFT, USABLE, BLOCKED: history kept
    with pytest.raises(store.FeatureError, match="unregistered@1 \\(not registered\\)"):
        store.require_usable(conn, [("unregistered", "1")])
    for bad in (("SOMETIMES", "owner", "x"), ("USABLE", "", "x"), ("USABLE", "owner", " ")):
        with pytest.raises(store.FeatureError):
            store.set_status(conn, "ret_20d", "1", bad[0], by=bad[1], reason=bad[2], now=NOW)
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("UPDATE feature_status SET reason='edited'")
    with pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        conn.execute("DELETE FROM feature_definition")


def test_a_month_is_materialised_once_in_one_transaction_and_a_rerun_writes_nothing(env):
    conn, ids = env
    store.register_all(conn, NOW)
    run = store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=DS,
        code_commit="abc",
        bars_by_instrument=history(ids),
        now=NOW,
    )
    assert run is not None
    rows = conn.execute(
        "SELECT instrument_id, day, value, available_at FROM feature_value WHERE run_id=%s ORDER BY 1, 2",
        (run,),
    ).fetchall()
    days = [d for d in sessions() if d.month == 1 and d.year == 2026]
    assert {r[1] for r in rows} == set(days) and len(rows) == 2 * len(
        days
    )  # the January sessions of both instruments, warm-up already behind them
    first = next(r for r in rows if r[0] == ids[0] and r[1] == days[0])
    prior = sessions()[sessions().index(days[0]) - 5]
    assert first[2] == q(
        D(100 + sessions().index(days[0])) / D(100 + sessions().index(prior)) - 1
    )  # the formula, from history before the month
    again = store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=DS,
        code_commit="abc",
        bars_by_instrument=history(ids),
        now=NOW,
    )
    assert again is None and conn.execute("SELECT count(*) FROM feature_run").fetchone() == (1,)
    other = store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=OTHER,
        code_commit="abc",
        bars_by_instrument=history(ids),
        now=NOW,
    )
    assert (
        other is not None and other != run
    )  # another dataset gets its own immutable materialisation


def test_reading_returns_exactly_the_datasets_values_and_raises_instead_of_substituting(env):
    conn, ids = env
    store.register_all(conn, NOW)
    store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=DS,
        code_commit="abc",
        bars_by_instrument=history(ids),
        now=NOW,
    )
    got = store.read_features(conn, "ret_5d", "1", DS, ids, date(2026, 1, 5), date(2026, 1, 9))
    assert (
        sorted({d for _, d in got}) == [date(2026, 1, d) for d in range(5, 10)] and len(got) == 10
    )
    assert len(store.values_hash(got)) == 64 and store.values_hash(got) == store.values_hash(
        dict(got)
    )
    with pytest.raises(
        store.FeatureError,
        match="no completed run of ret_5d@1 for dataset bbbbbbbbbbbb in: 2026-01",
    ):
        store.read_features(
            conn, "ret_5d", "1", OTHER, ids, date(2026, 1, 5), date(2026, 1, 9)
        )  # never another snapshot's values
    with pytest.raises(store.FeatureError, match="2026-02"):
        store.read_features(
            conn, "ret_5d", "1", DS, ids, date(2026, 1, 20), date(2026, 2, 3)
        )  # February was never computed
    with pytest.raises(store.FeatureError, match="not registered"):
        store.read_features(conn, "ret_5d", "9", DS, ids, date(2026, 1, 5), date(2026, 1, 9))


def test_a_month_that_reaches_the_global_holdout_is_refused_and_a_bad_request_is_named(env):
    conn, ids = env
    store.register_all(conn, NOW)
    with pytest.raises(store.FeatureError, match="reaches the global holdout"):
        store.materialise_month(
            conn,
            "ret_5d",
            "1",
            date(2026, 3, 1),
            dataset_sha256=DS,
            code_commit="abc",
            bars_by_instrument=history(ids),
            now=NOW,
        )
    with pytest.raises(store.FeatureError, match="first day"):
        store.materialise_month(
            conn,
            "ret_5d",
            "1",
            date(2026, 1, 15),
            dataset_sha256=DS,
            code_commit="abc",
            bars_by_instrument=history(ids),
            now=NOW,
        )
    assert conn.execute("SELECT count(*) FROM feature_run").fetchone() == (0,)


def test_a_failing_month_is_recorded_as_failed_and_invalidates_nothing(env, monkeypatch):
    conn, ids = env
    store.register_all(conn, NOW)
    store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=DS,
        code_commit="abc",
        bars_by_instrument=history(ids),
        now=NOW,
    )
    f = registry.DEFINITIONS["ret_20d"]

    def boom(sessions_, bars):
        raise ArithmeticError("division went wrong")

    import dataclasses

    monkeypatch.setitem(registry.DEFINITIONS, "ret_20d", dataclasses.replace(f, compute=boom))
    with pytest.raises(store.FeatureError, match="ret_20d@1 2026-01 failed: division went wrong"):
        store.materialise_month(
            conn,
            "ret_20d",
            "1",
            JAN,
            dataset_sha256=DS,
            code_commit="abc",
            bars_by_instrument=history(ids),
            now=NOW,
        )
    assert conn.execute(
        "SELECT status, error FROM feature_run ORDER BY run_id DESC LIMIT 1"
    ).fetchone() == ("failed", "division went wrong")
    assert conn.execute("SELECT count(*) FROM feature_run WHERE status='complete'").fetchone() == (
        1,
    )  # the earlier month is untouched


def test_bars_come_from_a_real_reader_with_adjusted_prices_and_their_visibility_time(env):
    conn, ids = env
    days = [d for d in sessions() if d < date(2026, 1, 20)]
    put_bars(conn, ids[0], {d: D(100 + i) for i, d in enumerate(days)})
    reader = BarReader(conn, source="nse")
    bars = store.bars_from_reader(reader, ids[0], date(2026, 1, 16))
    assert sorted(bars) == [d for d in days if d <= date(2026, 1, 16)]
    b = bars[days[3]]
    assert b.close == D(103) and b.raw_close == D(103) and b.raw_volume == D(10_000_000)
    assert (
        b.available_at
        == datetime(b.day.year, b.day.month, b.day.day, 3, 45, tzinfo=UTC) + reader.visible_after
    )  # bar-open plus the publish lag
    store.register_all(conn, NOW)
    run = store.materialise_month(
        conn,
        "ret_5d",
        "1",
        JAN,
        dataset_sha256=DS,
        code_commit="abc",
        bars_by_instrument={ids[0]: bars},
        now=NOW,
    )
    assert (
        run is not None
        and conn.execute("SELECT count(*) FROM feature_value WHERE run_id=%s", (run,)).fetchone()[0]
        > 0
    )


def test_a_fundamental_feature_can_be_described_and_blocked_but_never_made_usable_in_phase_one(env):
    conn, _ = env
    fid = conn.execute(
        "INSERT INTO feature_definition (name, version, manifest, manifest_sha256, created_at) VALUES ('pe_ttm','1','{\"family\": \"fundamental\"}','h',%s) RETURNING feature_id",
        (NOW,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO feature_status (feature_id, status, reason, set_by, at) VALUES (%s,'BLOCKED','fundamentals prerequisites not met','system',%s)",
        (fid, NOW),
    )
    assert store.status(conn, "pe_ttm", "1") == "BLOCKED"
    with pytest.raises(store.FeatureError, match="only price and volume features"):
        store.set_status(conn, "pe_ttm", "1", "USABLE", by="owner", reason="wanted it", now=NOW)
    with pytest.raises(store.FeatureError, match=r"pe_ttm@1 \(BLOCKED\)"):
        store.require_usable(conn, [("pe_ttm", "1")])

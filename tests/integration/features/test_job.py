# ruff: noqa: E501
import dataclasses
from datetime import UTC, date, datetime

import pytest

from algo.data import freeze as freeze_mod
from algo.data.readiness import Readiness, Reason
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.features import job, registry, store
from algo.research import holdout_lock
from tests.integration.features.test_store import LOCK, NOW, sessions
from tests.support.bt import put_bars
from tests.support.research_lock import write_lock_file

pytestmark = pytest.mark.integration
JAN, FEB, MAR = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)
USABLE = ("ret_5d", "ret_20d")
ALL_READY = lambda conn, needs: Readiness()  # noqa: E731


@pytest.fixture
def world(conn, monkeypatch, tmp_path):
    migrate(conn)
    monkeypatch.setattr(holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "lock.json", LOCK))
    holdout_lock.anchor(conn, LOCK, by="owner", reason="test", now=NOW)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = [repo.add_instrument(x, s) for s in ("AAA", "BBB")]
    days = sessions()
    for k, i in enumerate(ids):
        put_bars(conn, i, {d: 100 + 100 * k + n for n, d in enumerate(days)})
    store.register_all(conn, NOW)
    for n in USABLE:
        store.set_status(conn, n, "1", "USABLE", by="owner", reason="test", now=NOW)
    fid = freeze_mod.take(conn, "nse", days[-1], datetime(2026, 11, 7, tzinfo=UTC), "test freeze")
    return conn, ids, fid


def runs(conn, status="complete"):
    return conn.execute("SELECT count(*) FROM feature_run WHERE status=%s", (status,)).fetchone()[0]


def go(conn, fid, **kw):
    kw.setdefault("ready", ALL_READY)
    return job.run(conn, fid, JAN, NOW, "abc", **kw)


def test_only_usable_features_and_never_a_holdout_month_and_a_rerun_writes_nothing(world):
    conn, _, fid = world
    r = go(conn, fid)
    # the freeze runs into March, the holdout starts 2026-03-01: only January and February are computed
    assert r.status == "complete" and sorted(r.computed) == sorted(
        [(n, m) for n in USABLE for m in ("2026-01", "2026-02")]
    )
    assert set(r.skipped) == set(registry.DEFINITIONS) - set(USABLE) and runs(conn) == 4
    values = conn.execute("SELECT count(*), max(day) FROM feature_value").fetchone()
    assert values[1] < LOCK.holdout_start
    again = go(conn, fid)
    assert (again.computed, again.already, runs(conn)) == ([], 4, 4)
    assert conn.execute("SELECT count(*) FROM feature_value").fetchone()[0] == values[0]


def test_a_crash_mid_month_leaves_no_partial_month_and_the_next_run_redoes_exactly_that_month(
    world, monkeypatch
):
    conn, _, fid = world
    real = store.materialise_month
    calls = []

    def dying(conn_, name, version, month, **kw):
        if (name, month) == ("ret_20d", FEB):
            raise KeyboardInterrupt(
                "killed"
            )  # not a FeatureError: nothing in the job may swallow it
        calls.append((name, month))
        return real(conn_, name, version, month, **kw)

    monkeypatch.setattr(store, "materialise_month", dying)
    with pytest.raises(KeyboardInterrupt):
        go(conn, fid)
    done = runs(conn)
    assert (
        done == 3
        and not conn.execute(
            "SELECT 1 FROM feature_run WHERE status='complete' AND rows IS NULL"
        ).fetchone()
    )
    monkeypatch.setattr(store, "materialise_month", real)
    r = go(conn, fid)
    assert r.computed == [("ret_20d", "2026-02")] and r.already == 3 and runs(conn) == 4


def test_a_failed_month_is_recorded_and_invalidates_nothing_complete(world, monkeypatch):
    conn, _, fid = world
    go(conn, fid)
    assert runs(conn) == 4
    d = registry.DEFINITIONS["ret_5d"]
    monkeypatch.setitem(
        registry.DEFINITIONS, "ret_5d", dataclasses.replace(d, compute=lambda *a: 1 / 0)
    )
    # a new freeze is a new dataset, so everything is attempted again; ret_5d now blows up, ret_20d does not
    fid2 = freeze_mod.take(conn, "nse", sessions()[-2], datetime(2026, 11, 8, tzinfo=UTC), "second")
    r = go(conn, fid2)
    assert r.status == "failed" and len(r.failed) == 2 and all("ret_5d" in f for f in r.failed)
    assert (
        runs(conn, "failed") == 2 and runs(conn) == 6
    )  # the first dataset's four months and ret_20d on the second


def test_a_pause_request_takes_effect_at_the_next_month_boundary_with_finished_months_intact(world):
    conn, _, fid = world
    seen = []

    def busy(now):
        seen.append(1)
        return "run_paper.py is running" if len(seen) > 2 else None

    r = go(conn, fid, busy=busy)
    assert (r.status, r.paused_because) == ("paused", "run_paper.py is running")
    assert runs(conn) == 2  # two units finished, the third was never started
    r = go(conn, fid)
    assert r.status == "complete" and r.already == 2 and runs(conn) == 4


def test_it_refuses_when_the_input_data_is_not_ready_and_writes_nothing(world):
    conn, _, fid = world
    with pytest.raises(job.JobRefused, match="not ready: STALE: too old"):
        go(conn, fid, ready=lambda c, n: Readiness([Reason("STALE", "too old")]))
    assert runs(conn) == 0 and runs(conn, "failed") == 0


def test_an_unknown_freeze_is_refused_and_a_freeze_wholly_in_the_holdout_does_nothing(world):
    conn, _, fid = world
    from uuid import uuid4

    with pytest.raises(job.JobRefused, match="no such freeze"):
        go(conn, uuid4())
    with pytest.raises(job.JobRefused, match="no such freeze"):
        job.dataset_sha256(conn, uuid4(), [])
    r = job.run(
        conn, fid, date(2026, 3, 1), NOW, "abc", ready=ALL_READY
    )  # first month is already the holdout
    assert (r.computed, r.already, runs(conn)) == ([], 0, 0)


def test_the_job_issues_writes_only_to_the_feature_tables(world):
    conn, _, fid = world
    seen = []

    class Rec:
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, *a, **k):
            seen.append(str(sql))
            return self.inner.execute(sql, *a, **k)

        def cursor(self, *a, **k):
            outer = self

            class C:
                def __init__(self, c):
                    self.c = c

                def __enter__(self):
                    return self

                def __exit__(self, *e):
                    return self.c.__exit__(*e)

                def executemany(self, sql, rows):
                    seen.append(str(sql))
                    return self.c.executemany(sql, rows)

            return C(outer.inner.cursor(*a, **k))

        def __getattr__(self, n):
            return getattr(self.inner, n)

    go(Rec(conn), fid)
    writes = [s for s in seen if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert writes and all(("feature_run" in s or "feature_value" in s) for s in writes)


def test_busy_reason_and_month_arithmetic():
    mon_10am = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)  # 10:00 IST on a Monday
    night = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)  # 22:30 IST
    sat = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)
    assert (
        job.busy_reason(night, ["uv run python scripts/run_paper.py"]) == "run_paper.py is running"
    )
    assert job.busy_reason(night, ["x/paper_orders.py --db y"]) == "paper_orders.py is running"
    assert job.busy_reason(mon_10am, []) == "market hours"
    assert job.busy_reason(night, ["unrelated"]) is None and job.busy_reason(sat, []) is None
    assert job.months_through(date(2026, 1, 15), date(2026, 3, 30)) == [
        JAN,
        FEB,
    ]  # March is not whole yet
    assert job.months_through(date(2026, 1, 1), date(2026, 3, 31)) == [JAN, FEB, MAR]
    assert job.months_through(date(2025, 12, 1), date(2026, 1, 31))[-1] == JAN  # across a year end

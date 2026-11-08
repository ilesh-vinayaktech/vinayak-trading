"""The strategy through the real engine and bar reader. ENGINEERING_TEST_ONLY: synthetic prices,
never a strategy experiment, never registered."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import (
    IntervalMembership,
    MomentumParams,
    Nifty200TrendMomentum,
)
from tests.support.bt import ZERO, add_action, put_bars

pytestmark = pytest.mark.integration

N_SESSIONS = 330
FIRST = date(2024, 1, 1)
P = MomentumParams(lookback=126, trend_sma=100, holdings=20)


def sessions():
    out, d = [], FIRST
    while len(out) < N_SESSIONS:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions()
START, END = DAYS[260], DAYS[-1]


def path(slope, split_at=None):
    p, out = D(100), {}
    for i, d in enumerate(DAYS):
        out[d] = p / 2 if split_at is not None and i >= split_at else p
        p *= 1 + D(slope)
    return out


@pytest.fixture
def market(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    for k in range(22):
        iid = repo.add_instrument(x, f"S{k:02d}")
        repo.add_alias(iid, "nse", f"S{k:02d}", date(2000, 1, 1))
        ids.append(iid)
    return conn, ids


def seed(conn, ids, split_on=None):
    for k, iid in enumerate(ids):
        slope = str(0.0006 + k * 0.00003) if k < 14 else "-0.0004"
        at = 200 if iid == split_on else None
        put_bars(conn, iid, path(slope, at))
    if split_on is not None:
        add_action(conn, split_on, DAYS[200], "split", num=D(2), den=D(1))


def go(conn, ids):
    s = Nifty200TrendMomentum(
        P, IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
    )
    cfg = BacktestConfig(start=START, end=END, initial_cash=D(1_000_000), cost=ZERO)
    return s, run_backtest(conn, s, cfg)


def test_runs_end_to_end_and_the_books_reconcile(market):
    conn, ids = market
    seed(conn, ids)
    s, r = go(conn, ids)
    assert r.trades and r.ledger_reconciled and r.accounting_complete
    held = {i for i, q in r.final_positions.items() if q > 0}
    assert held <= set(ids[:14]) and len(held) == 14  # only up-trending names, 14 qualify
    want = [d for p, d in zip(DAYS[260:-2], DAYS[261:-1], strict=True) if d.month != p.month]
    assert [a["day"] for a in s.audit] == [str(d) for d in want]  # month starts only
    assert all(a["breadth"] >= 50 for a in s.audit)
    assert r.final_cash > 0  # 6 unfilled slots stay cash


def test_replay_is_byte_identical(market):
    conn, ids = market
    seed(conn, ids)
    (s1, a), (s2, b) = go(conn, ids), go(conn, ids)
    assert a.result_hash == b.result_hash and s1.audit == s2.audit


def test_a_split_does_not_look_like_a_momentum_crash(market):
    conn, ids = market
    seed(conn, ids, split_on=ids[13])  # raw price halves at DAYS[200]; the 2:1 split is on record
    s, r = go(conn, ids)
    assert ids[13] in s.audit[0]["selected"]  # the split-adjusted path is unbroken
    assert r.ledger_reconciled and not r.unmodelled


def test_without_the_recorded_action_the_same_drop_does_hurt(market):
    conn, ids = market
    for k, iid in enumerate(ids):  # control: identical raw halving but NO corporate action row
        slope = str(0.0006 + k * 0.00003) if k < 14 else "-0.0004"
        put_bars(conn, iid, path(slope, 200 if k == 13 else None))
    s, _ = go(conn, ids)
    assert ids[13] not in s.audit[0]["selected"]


def test_orchestrated_engineering_run_replays_to_the_same_manifest(market):
    from algo.research.run import Purpose, execute

    conn, ids = market
    seed(conn, ids)
    cfg = BacktestConfig(start=START, end=END, initial_cash=D(1_000_000), cost=ZERO)

    def one():
        members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
        return execute(
            conn, Nifty200TrendMomentum(P, members), cfg,
            purpose=Purpose.ENGINEERING_TEST_ONLY, code_version="test",
        )  # fmt: skip

    a, b = one(), one()
    assert a.manifest == b.manifest and a.manifest["purpose"] == "ENGINEERING_TEST_ONLY"
    assert a.manifest["result_hash"] == a.result.result_hash
    assert len(a.manifest["dataset_fingerprint"]) == 64

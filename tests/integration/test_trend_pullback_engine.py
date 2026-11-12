"""The pullback strategy through the real engine and bar reader. ENGINEERING_TEST_ONLY: synthetic prices,
never a strategy experiment, never registered."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from tests.support.bt import ZERO, put_bars

pytestmark = pytest.mark.integration

N_SESSIONS = 360
FIRST = date(2024, 1, 1)
P = TrendPullbackParams(max_positions=5)
UP = 14  # the first 14 names trend up with regular pullbacks; the rest fall steadily


def sessions():
    out, d = [], FIRST
    while len(out) < N_SESSIONS:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions()
START, END = DAYS[250], DAYS[-1]


def sawtooth(k: int) -> dict[date, D]:
    """Rises 0.4% a day; every 30 sessions (staggered by `k`) it drops 3% a day for four days."""
    p, out = D(100), {}
    for i, d in enumerate(DAYS):
        out[d] = p
        in_dip = i >= 200 and (i + k) % 30 < 4
        p *= D("0.97") if in_dip else D("1.004")
    return out


def falling() -> dict[date, D]:
    p, out = D(100), {}
    for d in DAYS:
        out[d] = p
        p *= D("0.9985")
    return out


@pytest.fixture
def market(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    for k in range(20):
        iid = repo.add_instrument(x, f"S{k:02d}")
        repo.add_alias(iid, "nse", f"S{k:02d}", date(2000, 1, 1))
        put_bars(conn, iid, sawtooth(k) if k < UP else falling())
        ids.append(iid)
    return conn, ids


def go(conn, ids):
    s = TrendPullback(P, IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids]))
    cfg = BacktestConfig(start=START, end=END, initial_cash=D(1_000_000), cost=ZERO)
    return s, run_backtest(conn, s, cfg)


def test_it_trades_the_pullbacks_decides_every_session_and_the_books_reconcile(market):
    conn, ids = market
    s, r = go(conn, ids)
    assert r.trades and r.ledger_reconciled and r.accounting_complete
    days = [a["day"] for a in s.audit]
    assert days == sorted(set(days)) and len(days) >= 100  # a decision on (nearly) every session
    bought = {iid for a in s.audit for iid in a["entries"]}
    assert bought and bought <= set(
        ids[:UP]
    )  # only up-trending names; the falling ones fail the trend test
    assert any(a["exits"] for a in s.audit)  # and they are sold again once they recover
    assert all(len(a["held"]) <= P.max_positions for a in s.audit)


def test_replay_is_byte_identical(market):
    conn, ids = market
    (s1, a), (s2, b) = go(conn, ids), go(conn, ids)
    assert a.result_hash == b.result_hash and s1.audit == s2.audit


def test_orchestrated_engineering_run_replays_to_the_same_manifest(market):
    from algo.research.run import Purpose, execute

    conn, ids = market
    cfg = BacktestConfig(start=START, end=END, initial_cash=D(1_000_000), cost=ZERO)

    def one():
        members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
        return execute(
            conn,
            TrendPullback(P, members),
            cfg,
            purpose=Purpose.ENGINEERING_TEST_ONLY,
            code_version="test",
        )

    a, b = one(), one()
    assert a.manifest == b.manifest and a.manifest["purpose"] == "ENGINEERING_TEST_ONLY"
    assert a.manifest["strategy"]["id"] == "trend_pullback"


def test_the_caller_can_pin_the_price_reader_so_the_environment_does_not_choose_the_source(market):
    from algo.data.reader import BarReader

    conn, ids = market
    s = TrendPullback(P, IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids]))
    cfg = BacktestConfig(start=START, end=END, initial_cash=D(1_000_000), cost=ZERO)
    on_nse = run_backtest(conn, s, cfg, reader=BarReader(conn, source="nse"))
    assert (
        on_nse.result_hash == run_backtest(conn, s, cfg).result_hash
    )  # the default here is bhavcopy: the same
    on_kite = run_backtest(
        conn, s, cfg, reader=BarReader(conn, source="kite", publish_lag=timedelta(0))
    )
    assert not on_kite.trades and len(on_kite.blocked) == len(
        ids
    )  # this data has no Kite bars: every name is blocked

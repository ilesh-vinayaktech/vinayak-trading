"""Regression backtest around an ISIN change: signals see ONE continuous issuer history, but orders and
fills use only the instrument that actually traded. Layout under test is the PROPOSED one (the old ISIN
owns the history before the change, the new ISIN from it, linked by SAME_ISSUER_ISIN_CHANGE).

Calendar (2023-24): Wed 27 Dec, Thu 28, Fri 29 Dec, Mon 1 Jan .. Thu 4 Jan (old ISIN trades), Fri 5 Jan
(new ISIN's first session; 10:1 split ex-date), Mon 8, Tue 9. A decision is taken at every close and
executed at the next open."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.backtest.engine import run_backtest
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.bt import add_action, cfg, put_bars
from tests.support.strategies import HoldParams, HoldWeights

pytestmark = pytest.mark.integration
CHANGE = date(2024, 1, 5)
OLD_DAYS = [
    date(2023, 12, 27), date(2023, 12, 28), date(2023, 12, 29),
    date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
]  # fmt: skip
NEW_DAYS = [date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9)]
ALL_DAYS = OLD_DAYS + NEW_DAYS


class SeesEverything(HoldWeights):
    """Holds fixed weights and records the full history the Context handed it at each decision."""

    def __init__(self, params):
        super().__init__(params)
        self.history = []  # (decision day, {iid: bars})

    def on_schedule(self, ctx):
        self.history.append((ctx.now().date(), ctx.data.history(self.params.ids, 30)))
        return super().on_schedule(ctx)


@pytest.fixture
def world(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    old, new, other = (repo.add_instrument(x, s) for s in ("NESTLE-OLD", "NESTLEIND", "AAA"))
    # raw prices: the old ISIN around 20,000; the new around 2,000 after the 10:1 split on the change date
    put_bars(
        conn, old, {d: (D(20000 + 10 * i), D(20000 + 10 * i + 5)) for i, d in enumerate(OLD_DAYS)}
    )
    put_bars(conn, new, {d: (D(2001 + i), D(2002 + i)) for i, d in enumerate(NEW_DAYS)})
    put_bars(conn, other, {d: D(100) for d in ALL_DAYS})
    add_action(conn, new, CHANGE, "split", num=D(10), den=D(1))
    conn.execute(
        "INSERT INTO corporate_action_relationship (relationship_type, source_instrument_id,"
        " target_instrument_id, target_symbol, effective_date, evidence, review_decision_id, recorded_at)"
        " VALUES ('SAME_ISSUER_ISIN_CHANGE', %s, %s, 'NESTLEIND', %s, '[\"NSE circular\"]'::jsonb, 15, now())",
        (old, new, CHANGE),
    )
    return conn, old, new, other


def run(world, weights):
    conn, old, new, other = world
    strat = SeesEverything(HoldParams(ids=(new, other), weights=(D(weights[0]), D(weights[1]))))
    res = run_backtest(
        conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
    )
    return strat, res


def test_the_signal_is_continuous_across_the_isin_change_before_the_new_isin_has_traded(world):
    conn, old, new, other = world
    strat, _ = run(world, ("0.5", "0.5"))
    seen = {d: h for d, h in strat.history}
    on_4_jan = seen[date(2024, 1, 4)][new]  # the new ISIN has not traded once yet
    assert len(on_4_jan) == 7  # the whole pre-change history is there for the signal
    assert {b.owner for b in on_4_jan} == {
        old
    }  # and every bar still says which instrument traded it
    # point in time: the split is known only from its ex-date (the conservative proxy), so on 4 Jan the
    # pre-change closes are still as traded; the adjustment appears when it becomes knowable
    assert [b.close for b in on_4_jan][:2] == [D(20005), D(20015)]
    on_8_jan = seen[date(2024, 1, 8)][new]
    assert [b.owner for b in on_8_jan] == [old] * 7 + [
        new
    ] * 2  # the new ISIN's own bars follow, never mixed
    assert [b.close for b in on_8_jan][:2] == [
        D("2000.5"),
        D("2001.5"),
    ]  # split adjusted, no jump at the change
    # 4 Jan close vs 5 Jan close: on one scale (raw they would differ tenfold: 20065 vs 2002)
    assert on_8_jan[6].close == D("2006.5")
    assert on_8_jan[7].close == D(2002)


def test_orders_and_fills_use_only_the_instrument_that_traded(world):
    conn, old, new, other = world
    _, res = run(world, ("0.5", "0.5"))
    new_trades = [t for t in res.trades if t.instrument_id == new]
    assert new_trades and all(
        t.day >= CHANGE for t in new_trades
    )  # never an order on the new ISIN before 5 Jan
    first = new_trades[0]
    assert (
        first.day == CHANGE
    )  # first valid execution: decision at the 4 Jan close, filled at the 5 Jan open
    assert first.price == D(
        "2001"
    )  # the NEW instrument's own raw open, not an old-ISIN price (20,000 range)
    assert all(
        t.instrument_id != old for t in res.trades
    )  # a position never silently becomes the old ISIN
    assert set(res.final_positions) == {new, other}
    other_days = [t.day for t in res.trades if t.instrument_id == other]
    assert other_days and other_days[0] == date(
        2023, 12, 28
    )  # the always-trading name: first possible open


def test_the_recorded_signal_sources_show_which_instruments_fed_each_name(world):
    conn, old, new, other = world
    _, res = run(world, ("0.5", "0.5"))
    assert res.signal_sources == {new: [old, new], other: [other]}


def test_without_an_isin_link_nothing_changes(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    a = repo.add_instrument(x, "AAA")
    put_bars(conn, a, {d: D(100) for d in ALL_DAYS})
    strat = SeesEverything(HoldParams(ids=(a,), weights=(D(1),)))
    res = run_backtest(
        conn, strat, cfg(start=ALL_DAYS[0], end=ALL_DAYS[-1], initial_cash=D(100000))
    )
    assert res.signal_sources == {a: [a]} and res.trades[0].instrument_id == a

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from algo.core.clock import SimClock
from algo.execution.flatten import flatten
from algo.execution.oms import Oms
from algo.execution.orders import State
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import FakeBroker

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


def build():
    broker, switch = FakeBroker(), KillSwitch()
    return Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW)), broker, switch


def hold(oms, broker, strategy, iid, qty):
    """A position the OMS really owns: its own order, sent and filled (negative: a sale that filled)."""
    side = Side.BUY if qty > 0 else Side.SELL
    o = oms.submit(
        f"hold{iid}",
        OrderRequest(strategy, iid, side, abs(qty)),
        Market(ltp=D(100)),
        Book(position_qty=max(qty, 0)),
        Day(),
    )
    oms.on_update(broker.move(o.order_id, "COMPLETE", abs(qty), D(100)))
    return o


def run(oms, positions, **kw):
    held = dict(positions)
    return flatten(
        oms,
        positions,
        market_of=lambda _i: Market(ltp=D(100)),
        book_of=lambda s, i: Book(position_qty=held[(s, i)]),
        day=Day(),
        **kw,
    )


def test_nothing_is_closed_unless_the_strategys_switch_is_flatten():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    placed = broker.place_calls
    r = run(oms, {("s1", 7): 10})
    assert r.orders == [] and r.skipped == ["s1"] and broker.place_calls == placed
    switch.cancel("s1", by="jane", reason="r", now=NOW)  # CANCEL is not FLATTEN
    assert run(oms, {("s1", 7): 10, ("s1", 8): 1}).skipped == ["s1"]  # named once


def test_flatten_sends_one_reduce_only_order_per_position_long_sells_short_buys_zero_is_ignored():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    hold(oms, broker, "s1", 8, -4)
    switch.flatten("s1", by="jane", reason="fire", now=NOW, emergency_override=True)
    r = run(oms, {("s1", 7): 10, ("s1", 8): -4, ("s1", 9): 0})
    assert [(o.instrument_id, o.side, o.qty, o.price, o.state) for o in r.orders] == [
        (7, Side.SELL, 10, None, State.SUBMITTED),
        (8, Side.BUY, 4, None, State.SUBMITTED),
    ]
    assert broker.place_calls == 4 and r.skipped == []  # two positions built, two closed


def test_the_closing_price_policy_is_the_callers():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    switch.flatten(None, by="jane", reason="fire", now=NOW, emergency_override=True)
    r = run(oms, {("s1", 7): 10}, price_of=lambda _i, side: D(99) if side is Side.SELL else D(101))
    assert r.orders[0].price == D(99)


def test_running_it_again_never_sends_a_second_closing_order_but_a_new_flatten_event_does():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    switch.flatten("s1", by="jane", reason="fire", now=NOW, emergency_override=True)
    first = run(oms, {("s1", 7): 10}).orders[0]
    again = run(oms, {("s1", 7): 10}).orders[0]
    assert (
        again.order_id == first.order_id and broker.place_calls == 2
    )  # the buy and one closing order
    assert broker.cancel_calls == []  # its own closing order is not cancelled by the repeat
    oms.on_update(broker.move(first.order_id, "COMPLETE", 10, D(100)))
    later = NOW + timedelta(hours=1)
    switch.resume("s1", by="jane", reason="ok", now=later)
    bought = oms.submit(
        "again", OrderRequest("s1", 7, Side.BUY, 5), Market(ltp=D(100)), Book(), Day()
    )
    oms.on_update(broker.move(bought.order_id, "COMPLETE", 5, D(100)))
    switch.flatten("s1", by="jane", reason="again", now=later, emergency_override=True)
    second = run(oms, {("s1", 7): 5}).orders[0]
    assert second.order_id != first.order_id and second.qty == 5


def test_the_strategys_other_open_orders_are_cancelled_first_and_other_strategies_left_alone():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    mine = oms.submit("buy", OrderRequest("s1", 7, Side.BUY, 5), Market(ltp=D(100)), Book(), Day())
    other = oms.submit("o", OrderRequest("s2", 7, Side.BUY, 5), Market(ltp=D(100)), Book(), Day())
    switch.flatten("s1", by="jane", reason="fire", now=NOW, emergency_override=True)
    r = run(oms, {("s1", 7): 10, ("s2", 7): 3})
    assert broker.cancel_calls == [mine.broker_order_id]  # not s2's order, not the closing order
    assert other.order_id in oms.orders and r.skipped == ["s2"]


def test_flatten_never_closes_shares_the_strategy_did_not_buy_even_when_given_the_brokers_totals():
    oms, broker, switch = build()
    hold(oms, broker, "s1", 7, 10)
    switch.flatten("s1", by="jane", reason="fire", now=NOW, emergency_override=True)
    # the account holds 1,685 of 7 in total (10 bought by the platform), 50 of 8 (none the platform's), and the broker shows -3 of 9
    r = run(oms, {("s1", 7): 1685, ("s1", 8): 50, ("s1", 9): -3})
    assert [(o.instrument_id, o.side, o.qty) for o in r.orders] == [(7, Side.SELL, 10)]
    assert broker.place_calls == 2  # the buy and the one closing order

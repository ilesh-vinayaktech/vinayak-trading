"""Properties of the order lifecycle (TODO 5.2): the whole transition matrix, replay rebuilds the same order, a fill can never exceed the order, a settled order
never changes, and fills never go backwards -- under any sequence of broker updates, including nonsense ones."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from algo.core.clock import SimClock
from algo.execution.broker import BrokerOrder
from algo.execution.oms import STATUS, Oms
from algo.execution.orders import (
    ALLOWED,
    TERMINAL,
    Order,
    OrderError,
    OrderEvent,
    State,
    apply,
    client_order_id,
    replay,
)
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import FakeBroker

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
QTY = 10


def an_order(state: State, filled=0) -> Order:
    return Order("A1", "s1", 7, Side.BUY, QTY, None, state=state, filled_qty=filled, last_seq=3)


@pytest.mark.parametrize("src", list(State))
@pytest.mark.parametrize("dst", list(State))
def test_every_pair_of_states_is_allowed_exactly_when_the_table_says_so(src, dst):
    ev = OrderEvent("A1", 4, NOW, dst, "STATE", {})
    if dst in ALLOWED[src]:
        assert apply(an_order(src), ev).state is dst
    else:
        with pytest.raises(OrderError, match="cannot become"):
            apply(an_order(src), ev)


def test_a_settled_order_allows_nothing_and_an_unknown_one_allows_everything_the_broker_can_say():
    assert all(ALLOWED[s] == frozenset() for s in TERMINAL)
    assert ALLOWED[State.UNKNOWN] >= {
        State.SUBMITTED,
        State.ACKED,
        State.PARTIALLY_FILLED,
        *TERMINAL,
    }


def fresh():
    broker, switch = FakeBroker(), KillSwitch()
    oms = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW))
    o = oms.submit("k", OrderRequest("s1", 7, Side.BUY, QTY), Market(ltp=D(100)), Book(), Day())
    return oms, broker, o


updates = st.lists(
    st.tuples(st.sampled_from(sorted(STATUS)), st.integers(min_value=0, max_value=QTY + 5)),
    max_size=14,
)


@settings(max_examples=150, deadline=None)
@given(updates)
def test_under_any_sequence_of_broker_updates_the_order_stays_sound(seq):
    oms, broker, o = fresh()
    oid = o.order_id
    last_filled, settled_at = 0, None
    for status, filled in seq:
        before = oms.orders[oid]
        try:
            oms.on_update(BrokerOrder("B1", oid, status, filled, D(100)))
        except OrderError:
            assert oms.orders[oid] == before  # a refused update changes nothing
        now = oms.orders[oid]
        assert 0 <= now.filled_qty <= QTY  # a fill never exceeds the order
        assert now.filled_qty >= last_filled  # and never goes backwards
        last_filled = now.filled_qty
        if settled_at is not None:
            assert now == settled_at  # a settled order never changes again
        elif now.state in TERMINAL:
            settled_at = now
        assert replay(oms.events[oid]) == now  # the log alone rebuilds the same order


def test_a_broker_reporting_more_filled_than_ordered_is_refused_and_changes_nothing():
    oms, broker, o = fresh()
    before = oms.orders[o.order_id]
    with pytest.raises(OrderError, match="exceeds"):
        oms.on_update(BrokerOrder("B1", o.order_id, "COMPLETE", QTY + 1, D(100)))
    assert oms.orders[o.order_id] == before and replay(oms.events[o.order_id]) == before
    assert client_order_id("s1", "k") == o.order_id and replace(before, qty=QTY) == before

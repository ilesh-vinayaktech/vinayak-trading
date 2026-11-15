from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.execution.orders import (
    ALLOWED,
    TERMINAL,
    OrderError,
    OrderEvent,
    State,
    apply,
    client_order_id,
    replay,
)
from algo.risk.model import Side

T = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
NEW = {"strategy_id": "s1", "instrument_id": 7, "side": "BUY", "qty": 10, "price": None}


def ev(seq, state=None, kind="STATE", **data):
    return OrderEvent("o1", seq, T, state, kind, data)


def new():
    return ev(0, None, "NEW", **NEW)


def test_client_order_ids_are_deterministic_unique_per_intent_and_broker_tag_safe():
    a = client_order_id("s1", "2026-11-16:INFY")
    assert a == client_order_id("s1", "2026-11-16:INFY")
    assert a != client_order_id("s1", "2026-11-16:TCS") and a != client_order_id(
        "s2", "2026-11-16:INFY"
    )
    assert len(a) == 20 and a.isalnum() and a.isupper()


def test_an_order_is_the_fold_of_its_events():
    o = replay(
        [
            new(),
            ev(1, State.SUBMITTING),
            ev(2, State.SUBMITTED, broker_order_id="B1"),
            ev(3, State.ACKED),
            ev(4, State.PARTIALLY_FILLED, filled_qty=4, avg_price=D(100)),
            ev(5, State.PARTIALLY_FILLED, filled_qty=7, avg_price=D("100.5")),
            ev(6, State.FILLED, filled_qty=10, avg_price=D("100.4")),
        ]
    )
    assert (o.state, o.filled_qty, o.avg_price, o.broker_order_id, o.last_seq) == (
        State.FILLED,
        10,
        D("100.4"),
        "B1",
        6,
    )
    assert (o.strategy_id, o.instrument_id, o.side, o.qty) == ("s1", 7, Side.BUY, 10)
    assert o.is_terminal and not o.is_open


def test_a_replay_of_a_prefix_is_the_order_as_it_was_then():
    events = [new(), ev(1, State.SUBMITTING), ev(2, State.SUBMITTED, broker_order_id="B1")]
    assert replay(events[:2]).state is State.SUBMITTING and replay(events).is_open


def test_events_that_do_not_move_the_state_are_kept_in_the_sequence():
    o = replay([new(), ev(1, None, "NOTE", text="x"), ev(2, State.SUBMITTING)])
    assert o.state is State.SUBMITTING and o.last_seq == 2


def test_an_order_must_start_with_new_at_sequence_zero():
    with pytest.raises(OrderError, match="starts with"):
        apply(None, ev(1, State.SUBMITTING))
    with pytest.raises(OrderError, match="starts with"):
        apply(None, ev(0, State.SUBMITTING))
    with pytest.raises(OrderError, match="no events"):
        replay([])


def test_a_gap_or_a_repeat_in_the_sequence_is_refused():
    o = apply(None, new())
    with pytest.raises(OrderError, match="does not follow"):
        apply(o, ev(2, State.SUBMITTING))
    with pytest.raises(OrderError, match="does not follow"):
        apply(o, ev(0, State.SUBMITTING))


def test_the_lifecycle_refuses_illegal_transitions():
    o = replay([new(), ev(1, State.SUBMITTING)])
    with pytest.raises(OrderError, match="cannot become"):
        apply(o, ev(2, State.FILLED))  # not acknowledged yet
    for state in TERMINAL:
        assert ALLOWED[state] == frozenset()  # terminal means terminal
    done = replay([new(), ev(1, State.REJECTED)])
    with pytest.raises(OrderError, match="cannot become"):
        apply(done, ev(2, State.SUBMITTING))


def test_an_unknown_order_can_become_anything_the_broker_says_it_is():
    unknown = replay([new(), ev(1, State.SUBMITTING), ev(2, State.UNKNOWN)])
    assert apply(unknown, ev(3, State.ACKED)).state is State.ACKED
    assert ALLOWED[State.UNKNOWN] >= {
        State.SUBMITTED,
        State.FILLED,
        State.CANCELLED,
        State.REJECTED,
        State.EXPIRED,
    }
    assert State.UNKNOWN not in ALLOWED[State.ACKED]  # only a submission can be ambiguous


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_only_a_tag_the_platform_could_have_made_counts_as_ours():
    from algo.execution.orders import is_platform_tag

    good = "A" + "0123456789ABCDEF123"  # 20 characters: A plus 19 hex digits
    assert len(good) == 20 and is_platform_tag(good)
    assert not is_platform_tag("B" + good[1:])  # wrong first letter
    assert not is_platform_tag(good[:-1])  # too short
    assert not is_platform_tag(good + "0")  # too long
    assert not is_platform_tag("A" + "G" * 19)  # not hex
    assert not is_platform_tag("Axxxxxxxxxxxxxxxxxxx".replace("x", "z"))
    assert not is_platform_tag("A" + "0" * 17 + "g0") and not is_platform_tag(
        "A" + "g" + "0" * 18
    )  # a bad digit anywhere, including the first after the letter
    assert not is_platform_tag("a" + good[1:])  # lower-case letter


def test_the_first_event_must_be_new_and_an_empty_log_cannot_be_replayed_and_the_messages_say_so():
    with pytest.raises(OrderError) as e:
        apply(None, ev(1, State.SUBMITTING))
    assert str(e.value) == "an order starts with its NEW event at sequence 0"
    with pytest.raises(OrderError) as e2:
        replay([])
    assert str(e2.value) == "no events"


def test_an_event_without_a_price_or_reason_keeps_the_ones_the_order_already_has():
    from decimal import Decimal

    o = apply(None, ev(0, None, "NEW", **NEW))
    o = apply(o, ev(1, State.SUBMITTING))
    o = apply(o, ev(2, State.SUBMITTED, broker_order_id="B1"))
    o = apply(
        o, ev(3, State.PARTIALLY_FILLED, filled_qty=3, avg_price=Decimal("99.5"), reason="partial")
    )
    o = apply(o, ev(4, None, "NOTE", text="x"))  # an event that says nothing about price or reason
    assert (o.avg_price, o.reason) == (Decimal("99.5"), "partial")


def test_a_letter_that_is_not_a_hex_digit_makes_a_tag_foreign_even_an_x():
    from algo.execution.orders import is_platform_tag

    assert not is_platform_tag("A" + "X" * 19) and not is_platform_tag("A" + "0" * 18 + "X")


def test_a_state_change_that_says_nothing_about_price_or_reason_keeps_what_the_order_had():
    from decimal import Decimal

    o = apply(None, ev(0, None, "NEW", **NEW))
    o = apply(o, ev(1, State.SUBMITTING))
    o = apply(o, ev(2, State.SUBMITTED, broker_order_id="B1"))
    o = apply(
        o, ev(3, State.PARTIALLY_FILLED, filled_qty=3, avg_price=Decimal("99.5"), reason="partial")
    )
    o = apply(o, ev(4, State.FILLED, filled_qty=10))  # no price, no reason in this one
    assert (o.state, o.filled_qty, o.avg_price, o.reason) == (
        State.FILLED,
        10,
        Decimal("99.5"),
        "partial",
    )

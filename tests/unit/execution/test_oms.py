from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.execution.broker import BrokerOrder
from algo.execution.oms import Oms
from algo.execution.orders import OrderError, State, client_order_id, replay
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import FailurePolicy, KillSwitch, Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import FakeBroker

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
MKT, BOOK0, DAY0 = Market(ltp=D(100)), Book(), Day()
REQ = OrderRequest("s1", 7, Side.BUY, 10)
REQ_ID = client_order_id("s1", "k1")


def build(script=(), limits=None, policy=None):
    broker, switch = FakeBroker(script), KillSwitch()
    oms = Oms(broker, RiskEngine(limits or Limits(), switch), SimClock(NOW), policy)
    return oms, broker, switch


def submit(oms, key="k1", req=REQ):
    return oms.submit(key, req, MKT, BOOK0, DAY0)


def cid(key="k1", strategy="s1"):
    return client_order_id(strategy, key)


def test_an_approved_order_is_sent_once_and_its_history_is_replayable():
    oms, broker, _ = build()
    o = submit(oms)
    assert (o.state, o.broker_order_id, o.order_id) == (State.SUBMITTED, "B1", cid())
    assert broker.place_calls == 1
    assert [e.state for e in oms.events[o.order_id]] == [
        None,
        State.SUBMITTING,
        None,
        State.SUBMITTED,
    ]  # NEW, the command, the attempt, the answer
    assert replay(oms.events[o.order_id]) == oms.orders[o.order_id]


def test_a_breached_order_never_reaches_the_broker():
    oms, broker, _ = build(limits=Limits(max_order_qty=5))
    o = submit(oms)
    assert o.state is State.REJECTED and o.reason == "risk: MAX_QTY"
    assert broker.place_calls == 0 and broker.book == {}


def test_a_paused_or_cancelled_strategy_sends_nothing_and_flatten_lets_only_closing_orders_out():
    oms, broker, switch = build()
    switch.pause("s1", by="jane", reason="r", now=NOW)
    assert submit(oms, "a").reason == "risk: PAUSED"
    switch.cancel(None, by="jane", reason="r", now=NOW)
    assert submit(oms, "b").state is State.REJECTED and broker.place_calls == 0
    switch.flatten(None, by="jane", reason="fire", now=NOW, emergency_override=True)
    closing = OrderRequest("s1", 7, Side.SELL, 10, reduce_only=True)
    assert oms.submit("c", closing, MKT, Book(position_qty=10), DAY0).state is State.SUBMITTED
    assert broker.place_calls == 1


def test_a_broker_rejection_is_final_and_says_why():
    oms, broker, _ = build(["reject"])
    o = submit(oms)
    assert (
        o.state is State.REJECTED and "insufficient margin" in o.reason and broker.place_calls == 1
    )


def test_submitting_the_same_intent_again_never_creates_a_second_order():
    oms, broker, _ = build()
    first = submit(oms)
    assert submit(oms) == first and broker.place_calls == 1
    assert submit(oms, "k2").order_id != first.order_id and broker.place_calls == 2


def test_a_timeout_makes_the_order_unknown_and_a_retry_of_the_intent_finds_it_instead_of_resending():
    oms, broker, _ = build(["timeout_after"])  # the broker took the order, the reply was lost
    o = submit(oms)
    assert o.state is State.UNKNOWN and "no answer" in o.reason
    again = submit(oms)  # the strategy retries the same intent
    assert again.state is State.ACKED and again.broker_order_id == "B1"
    assert broker.place_calls == 1 and len(broker.book) == 1  # no duplicate at the broker
    assert oms.alerts == []


def test_an_order_the_broker_never_got_stays_unknown_pauses_its_strategy_and_alerts_and_is_never_resent():
    oms, broker, switch = build(["timeout_before"])
    o = submit(oms)
    assert o.state is State.UNKNOWN
    again = submit(oms)
    assert again.state is State.UNKNOWN and broker.place_calls == 1  # not resent
    assert switch.mode("s1") is Mode.PAUSE and switch.mode("s2") is Mode.RUNNING
    assert len(oms.alerts) == 1 and cid() in oms.alerts[0] and "not found" in oms.alerts[0]
    assert any(e.kind == "NOTE" for e in oms.events[o.order_id])
    # new intents of the paused strategy are refused until a person resumes it
    assert submit(oms, "k2").reason == "risk: PAUSED"


def test_a_failed_lookup_is_unresolved_too():
    oms, broker, switch = build(["timeout_after"])
    submit(oms)
    broker.list_fails = True
    assert oms.resolve_unknown(cid()).state is State.UNKNOWN
    assert switch.mode("s1") is Mode.PAUSE and "lookup failed" in oms.alerts[0]


def test_resolving_an_order_that_is_not_unknown_changes_nothing():
    oms, _, _ = build()
    o = submit(oms)
    assert oms.resolve_unknown(o.order_id) == o


def test_only_a_person_can_end_an_unknown_order_without_the_brokers_word():
    oms, _, _ = build(["timeout_before"])
    o = submit(oms)
    done = oms.confirm_not_sent(o.order_id, by="jane", reason="checked the order book")
    assert done.state is State.CANCELLED and "jane" in done.reason
    with pytest.raises(OrderError, match="not UNKNOWN"):
        oms.confirm_not_sent(o.order_id, by="jane", reason="again")


def test_fills_arrive_in_any_order_and_duplicates_are_ignored():
    oms, broker, _ = build()
    o = submit(oms)
    ack = broker.move(o.order_id, "OPEN")
    assert oms.on_update(ack).state is State.ACKED
    assert oms.on_update(ack) is None  # duplicate
    partial = broker.move(o.order_id, "PARTIAL", 4, D(100))
    assert oms.on_update(partial).filled_qty == 4
    assert oms.on_update(partial) is None  # duplicate
    assert oms.on_update(ack) is None  # a late ACK after the partial fill
    assert (
        oms.on_update(BrokerOrder("B1", o.order_id, "PARTIAL", 2, D(100))) is None
    )  # an older, smaller fill
    more = broker.move(o.order_id, "PARTIAL", 7, D("100.5"))
    assert oms.on_update(more).filled_qty == 7
    done = broker.move(o.order_id, "COMPLETE", 10, D("100.4"))
    assert oms.on_update(done).state is State.FILLED
    assert (
        oms.on_update(broker.move(o.order_id, "PARTIAL", 9, D(100))) is None
    )  # nothing after a terminal state
    assert oms.ignored == 5
    final = oms.orders[o.order_id]
    assert (final.filled_qty, final.avg_price) == (10, D("100.4")) and replay(
        oms.events[o.order_id]
    ) == final


def test_a_fill_can_arrive_before_the_ack_and_an_unknown_order_takes_the_brokers_state():
    oms, broker, _ = build()
    o = submit(oms)
    assert (
        oms.on_update(broker.move(o.order_id, "COMPLETE", 10, D(100))).state is State.FILLED
    )  # straight from SUBMITTED
    oms2, broker2, _ = build(["timeout_after"])
    u = submit(oms2)
    assert oms2.on_update(broker2.move(u.order_id, "COMPLETE", 10, D(100))).state is State.FILLED


def test_an_update_for_an_order_we_never_sent_is_kept_aside_and_an_unknown_status_is_refused():
    oms, broker, _ = build()
    assert (
        oms.on_update(BrokerOrder("B9", "SOMEONEELSES", "OPEN")) is None and len(oms.orphans) == 1
    )
    o = submit(oms)
    with pytest.raises(OrderError, match="unknown broker status"):
        oms.on_update(BrokerOrder("B1", o.order_id, "WEIRD"))


def test_cancelling_asks_the_broker_and_waits_for_its_word():
    oms, broker, _ = build()
    a, b = submit(oms, "a"), submit(oms, "b", OrderRequest("s2", 8, Side.BUY, 1))
    done = submit(oms, "c")
    oms.on_update(broker.move(done.order_id, "COMPLETE", 10, D(100)))  # no longer open
    assert oms.cancel_open("s1") == [a.order_id]  # one strategy, open orders only
    assert (
        broker.cancel_calls == ["B1"] and oms.orders[a.order_id].state is State.SUBMITTED
    )  # not cancelled yet
    assert oms.cancel_open() == [a.order_id, b.order_id]  # all of them
    oms.on_update(broker.move(a.order_id, "CANCELLED"))
    assert oms.orders[a.order_id].state is State.CANCELLED


def test_a_cancel_the_broker_cannot_take_is_noted_and_the_order_stays_open():
    oms, broker, _ = build()
    o = submit(oms)
    broker.cancel_fails = True
    assert oms.cancel_open() == [] and oms.orders[o.order_id].is_open
    assert any(
        e.kind == "NOTE" and "cancel failed" in e.data["text"] for e in oms.events[o.order_id]
    )


def test_reconciliation_against_a_matching_broker_finds_nothing():
    oms, broker, switch = build()
    o = submit(oms)
    oms.on_update(broker.move(o.order_id, "PARTIAL", 3, D(100)))
    assert oms.reconcile() == [] and switch.mode("s1") is Mode.RUNNING


def test_an_order_the_risk_engine_refused_never_reached_the_broker_so_it_is_not_a_mismatch():
    oms, _, _ = build(limits=Limits(max_order_qty=1))
    assert submit(oms).state is State.REJECTED and oms.reconcile() == []


def test_every_kind_of_mismatch_is_found_named_and_recorded_and_pauses_trading_at_the_threshold():
    oms, broker, switch = build()
    a, b, c = submit(oms, "a"), submit(oms, "b"), submit(oms, "c")
    del broker.book[a.order_id]  # the broker has no such order
    broker.move(b.order_id, "CANCELLED")  # the broker says cancelled, the OMS has SUBMITTED
    oms.on_update(broker.move(c.order_id, "PARTIAL", 2, D(100)))
    broker.move(c.order_id, "PARTIAL", 5, D(100))  # more filled at the broker than the OMS knows
    broker.book["A" + "0" * 19] = BrokerOrder(
        "B99", "A" + "0" * 19, "OPEN"
    )  # an order the OMS never sent
    found = oms.reconcile(threshold=4)
    assert sorted(m.kind for m in found) == [
        "FILL_MISMATCH",
        "MISSING_AT_BROKER",
        "ORPHAN",
        "STATE_MISMATCH",
    ]
    assert switch.mode("anyone") is Mode.PAUSE and "4 mismatch" in oms.alerts[-1]
    assert [e.kind for e in oms.events[a.order_id]][-1] == "RECONCILED" and oms.events[a.order_id][
        -1
    ].data["result"] == "MISSING_AT_BROKER"


def test_a_few_mismatches_below_the_threshold_are_recorded_but_do_not_halt():
    oms, broker, switch = build()
    a = submit(oms)
    del broker.book[a.order_id]
    assert [m.kind for m in oms.reconcile(threshold=2)] == ["MISSING_AT_BROKER"]
    assert switch.mode("s1") is Mode.RUNNING and oms.alerts == []


def test_when_the_broker_cannot_be_read_trading_pauses():
    oms, broker, switch = build()
    submit(oms)
    broker.list_fails = True
    (m,) = oms.reconcile()
    assert (
        m.kind == "BROKER_UNREACHABLE"
        and switch.mode("s1") is Mode.PAUSE
        and "could not read" in oms.alerts[0]
    )


def test_the_failure_policy_decides_how_hard_an_ambiguous_order_is_answered():
    from algo.risk.killswitch import Failure

    oms, _, switch = build(
        ["timeout_before"], policy=FailurePolicy(actions={Failure.AMBIGUOUS_ORDER: Mode.CANCEL})
    )
    submit(oms)
    submit(oms)  # the lookup finds nothing
    assert switch.mode("s1") is Mode.CANCEL


class ListStore:
    """Keeps every event the OMS appends, like a table would."""

    def __init__(self):
        self.rows = []

    def append(self, ev):
        self.rows.append(ev)

    def load(self):
        out = {}
        for e in self.rows:
            out.setdefault(e.order_id, []).append(e)
        return out


def build_with(store, script=()):
    broker, switch = FakeBroker(script), KillSwitch()
    return Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), store=store), broker


def test_every_event_is_appended_to_the_store_and_a_new_oms_replays_the_same_orders():
    store = ListStore()
    oms, broker = build_with(store)
    a, b = submit(oms, "a"), submit(oms, "b")
    oms.on_update(broker.move(a.order_id, "PARTIAL", 4, D(100)))
    oms.cancel_open("s1")
    assert len(store.rows) == sum(len(v) for v in oms.events.values())
    restarted, broker2 = build_with(store)
    broker2.book = broker.book
    assert restarted.orders == oms.orders and restarted.events == oms.events
    assert (
        restarted.on_update(broker.move(a.order_id, "COMPLETE", 10, D(100))).state is State.FILLED
    )  # carries on from where it was
    assert (
        submit(restarted, "b") == restarted.orders[b.order_id] and broker2.place_calls == 0
    )  # the same intent: no second order


def test_an_order_the_broker_already_has_can_be_adopted_without_sending_anything():
    oms, broker = build_with(ListStore())
    placed = broker.book[REQ_ID] = BrokerOrder("B7", REQ_ID, "PARTIAL", 3, D(100))
    o = oms.adopt("k1", REQ, placed)
    assert (o.state, o.filled_qty, o.broker_order_id) == (
        State.PARTIALLY_FILLED,
        3,
        "B7",
    ) and broker.place_calls == 0
    assert oms.adopt("k1", REQ, placed) == o  # idempotent
    with pytest.raises(OrderError, match="not the tag"):
        oms.adopt(
            "other", REQ, placed
        )  # the broker order is not the one this intent would have sent
    assert replay(oms.events[o.order_id]) == o


def test_a_broker_reason_is_kept_on_the_order():
    oms, broker = build_with(ListStore())
    o = submit(oms)
    done = oms.on_update(BrokerOrder("B1", o.order_id, "REJECTED", reason="not enough cash"))
    assert done.state is State.REJECTED and done.reason == "not enough cash"


def test_the_oms_adds_up_its_own_fills_into_positions_and_a_cancel_can_spare_chosen_orders():
    oms, broker, _ = build()
    a, b, c = (
        submit(oms, "a"),
        submit(oms, "b", OrderRequest("s1", 7, Side.SELL, 4)),
        submit(oms, "c", OrderRequest("s1", 8, Side.BUY, 1)),
    )
    oms.on_update(broker.move(a.order_id, "COMPLETE", 10, D(100)))
    oms.on_update(broker.move(b.order_id, "COMPLETE", 4, D(100)))
    assert oms.positions() == {("s1", 7): 6}  # 10 bought, 4 sold; c has not filled
    assert oms.cancel_open("s1", keep={c.order_id}) == []
    assert oms.cancel_open("s1") == [c.order_id]


def test_differences_found_elsewhere_count_toward_the_threshold_like_order_mismatches():
    from algo.execution.reconciler import Portfolio, compare

    oms, broker, switch = build()
    o = submit(oms)
    oms.on_update(broker.orders()[0])  # the OMS has seen the broker's acknowledgement
    assert o.order_id in oms.orders
    extra = compare(Portfolio({7: 10}), Portfolio({7: 8}))
    found = oms.reconcile(extra=extra)
    assert [m.kind for m in found] == ["POSITION_MISMATCH"] and switch.mode("s1") is Mode.PAUSE
    assert "POSITION_MISMATCH" in oms.alerts[-1]


def test_an_order_placed_by_hand_is_never_cancelled_or_reconciled_but_a_platform_tag_we_do_not_know_is_reported():
    from algo.execution.broker import MANUAL_PREFIX

    oms, broker, switch = build()
    o = submit(oms)
    oms.on_update(broker.orders()[0])
    broker.book[f"{MANUAL_PREFIX}9"] = BrokerOrder(
        "B9", f"{MANUAL_PREFIX}9", "OPEN"
    )  # the owner's own order in the Kite app
    broker.book["someapp-77"] = BrokerOrder("B10", "someapp-77", "OPEN")  # another app's tag
    assert oms.reconcile() == [] and switch.mode("s1") is Mode.RUNNING
    assert oms.cancel_open("s1") == [o.order_id] and broker.cancel_calls == [
        "B1"
    ]  # only ours is cancelled
    broker.book["A" + "F" * 19] = BrokerOrder(
        "B11", "A" + "F" * 19, "OPEN"
    )  # looks like ours, but the OMS never sent it
    assert [m.kind for m in oms.reconcile()] == ["ORPHAN"]


def test_a_live_oms_refuses_to_sell_more_than_the_strategy_bought_itself():
    oms, broker, _ = build()
    oms.own_positions_only = True

    def sell(key, qty):
        return oms.submit(
            key, OrderRequest("s1", 7, Side.SELL, qty), MKT, Book(position_qty=1000), DAY0
        )

    r = sell("s0", 1)
    assert (
        r.state is State.REJECTED and "own position" in r.reason and broker.place_calls == 0
    )  # nothing bought yet: all 1000 held are someone else's
    buy = submit(oms, "b", OrderRequest("s1", 7, Side.BUY, 10))
    oms.on_update(broker.move(buy.order_id, "COMPLETE", 10, D(100)))
    first = sell("s1", 6)  # of the 10 it bought
    assert first.state is State.SUBMITTED
    assert sell("s2", 5).state is State.REJECTED  # 6 are already being sold: only 4 left to sell
    assert sell("s3", 4).state is State.SUBMITTED
    other = oms.submit("o", OrderRequest("s9", 7, Side.SELL, 1), MKT, Book(position_qty=5), DAY0)
    assert other.state is State.REJECTED  # another strategy's holdings are not this one's either
    oms.own_positions_only = False
    assert (
        sell("s4", 99).state is State.SUBMITTED
    )  # the paper path keeps its own book and is unchanged


# ---- the outbox: the SUBMITTING event is the durable command, an ATTEMPT event marks that it may have left the process ----
from tests.support.fake_broker import Crash  # noqa: E402


class CrashingStore(ListStore):
    """Dies instead of writing the event whose kind or state is named."""

    def __init__(self, die_on):
        super().__init__()
        self.die_on = die_on

    def append(self, ev):
        if self.die_on and self.die_on in (ev.kind, ev.state and ev.state.value):
            raise Crash
        super().append(ev)


def crashed_then_restarted(store, script=(), switch=None):
    """Run one submit until the crash, then start a fresh OMS on what was written. The broker's book survives the crash."""
    oms, broker = build_with(store, script)
    with pytest.raises(Crash):
        submit(oms)
    store.die_on = None
    again, broker2 = build_with(store)
    broker2.book = broker.book
    if switch is not None:
        again.risk.switch = switch
    return again, broker2


def test_a_crash_before_the_send_is_recovered_by_sending_once():
    again, broker = crashed_then_restarted(CrashingStore("ATTEMPT"))
    assert again.orders[REQ_ID].state is State.SUBMITTING and broker.place_calls == 0
    again.recover()
    assert again.orders[REQ_ID].state is State.SUBMITTED and broker.place_calls == 1
    again.recover()  # nothing left to do: never a second send
    assert broker.place_calls == 1


def test_a_crash_after_the_broker_took_the_order_finds_it_by_its_tag_and_never_resends():
    again, broker = crashed_then_restarted(CrashingStore("never"), script=["crash_after"])
    again.recover()
    assert again.orders[REQ_ID].state is State.ACKED and broker.place_calls == 0
    assert not again.alerts


def test_a_crash_after_the_attempt_that_the_broker_never_saw_is_unknown_pauses_and_is_not_resent():
    again, broker = crashed_then_restarted(CrashingStore("never"), script=["crash_before"])
    again.recover()
    o = again.orders[REQ_ID]
    assert o.state is State.UNKNOWN and broker.place_calls == 0
    assert again.risk.switch.mode("s1") is not Mode.RUNNING and again.alerts


def test_a_crash_before_the_risk_decision_was_written_rejects_the_order_and_sends_nothing():
    again, broker = crashed_then_restarted(CrashingStore("SUBMITTING"))
    assert again.orders[REQ_ID].state is State.NEW
    again.recover()
    o = again.orders[REQ_ID]
    assert o.state is State.REJECTED and broker.place_calls == 0


def test_an_unsent_order_found_on_restart_is_not_sent_when_the_strategy_has_been_paused_meanwhile():
    store = CrashingStore("ATTEMPT")
    switch = KillSwitch()
    switch.pause("s1", by="t", reason="stop", now=NOW)
    again, broker = crashed_then_restarted(store, switch=switch)
    again.recover()
    assert again.orders[REQ_ID].state is State.REJECTED and broker.place_calls == 0

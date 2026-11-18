from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.execution.broker import BrokerOrder
from algo.execution.oms import Mismatch, Oms
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


def test_a_finished_order_with_no_fill_that_the_broker_no_longer_lists_is_not_a_mismatch_but_a_lost_fill_is():
    oms, broker, _ = build()
    expired, cancelled, filled = submit(oms, "e"), submit(oms, "c"), submit(oms, "f")
    oms.on_update(broker.move(expired.order_id, "EXPIRED"))
    oms.on_update(broker.move(cancelled.order_id, "CANCELLED"))
    oms.on_update(broker.move(filled.order_id, "COMPLETE", 10, D(100)))
    for o in (expired, cancelled, filled):
        del broker.book[o.order_id]  # brokers drop old orders from their book
    assert [(m.kind, m.client_order_id) for m in oms.reconcile()] == [
        ("MISSING_AT_BROKER", filled.order_id)
    ]


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


def test_a_just_submitted_order_that_the_broker_lists_as_open_is_not_a_mismatch():
    oms, broker, switch = build()
    o = submit(oms)
    assert (
        oms.orders[o.order_id].state is State.SUBMITTED and broker.book[o.order_id].status == "OPEN"
    )
    assert (
        oms.reconcile() == [] and switch.mode("s1") is Mode.RUNNING
    )  # it only has not had its first update yet
    broker.move(o.order_id, "CANCELLED")
    assert [m.kind for m in oms.reconcile(threshold=9)] == [
        "STATE_MISMATCH"
    ]  # a real difference is still found


# ======================================================================================================================
# Found by mutation testing (2026-11-15): what the order log RECORDS, the exact words of every refusal and note, and the
# restart path's details. The OMS is the code that keeps the books straight, so its records are tested as records.
# ======================================================================================================================
def test_the_constructor_flag_turns_on_the_own_positions_rule_and_off_is_the_default():
    broker, switch = FakeBroker(), KillSwitch()
    live = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), own_positions_only=True)
    r = live.submit("s", OrderRequest("s1", 7, Side.SELL, 1), MKT, Book(position_qty=1000), DAY0)
    assert (r.state, r.reason) == (
        State.REJECTED,
        "own position: more than this strategy bought (shares held from elsewhere are never sold)",
    )
    paper = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW))
    assert paper.own_positions_only is False
    assert (
        paper.submit(
            "s", OrderRequest("s1", 7, Side.SELL, 1), MKT, Book(position_qty=1000), DAY0
        ).state
        is State.SUBMITTED
    )


def test_the_same_intent_again_returns_the_order_as_it_is_and_only_an_unknown_one_is_looked_up(
    monkeypatch,
):
    oms, broker, _ = build()
    first = submit(oms)
    monkeypatch.setattr(
        oms, "resolve_unknown", lambda oid: pytest.fail("a settled order must not be looked up")
    )
    assert submit(oms) == first and broker.place_calls == 1
    oms2, _, _ = build(script=["timeout_before"])
    unknown = submit(oms2)
    assert unknown.state is State.UNKNOWN
    seen = []
    monkeypatch.setattr(oms2, "resolve_unknown", lambda oid: seen.append(oid) or oms2.orders[oid])
    submit(oms2)
    assert seen == [cid()]


def test_the_day_and_the_clock_reach_the_risk_checks_and_every_refusal_code_is_in_the_reason():
    oms, broker, _ = build(limits=Limits(max_daily_orders=1))
    r = oms.submit("k", REQ, MKT, BOOK0, Day(orders=1))
    assert (r.state, r.reason) == (State.REJECTED, "risk: DAILY_ORDERS") and broker.place_calls == 0
    from datetime import time

    late = Limits(
        trading_hours=(time(9, 15), time(10, 0))
    )  # 10:30 IST on the test clock is after the close
    assert build(limits=late)[0].submit("k", REQ, MKT, BOOK0, DAY0).reason == "risk: HOURS"
    both = build(limits=Limits(max_order_qty=1, max_daily_orders=1))[0].submit(
        "k", REQ, MKT, BOOK0, Day(orders=1)
    )
    assert both.reason == "risk: MAX_QTY, DAILY_ORDERS"


def test_the_log_records_the_request_as_sent_with_the_clock_time_and_the_flag_that_a_restart_reads():
    oms, broker, _ = build()
    req = OrderRequest("s1", 7, Side.SELL, 4, D("99.5"), reduce_only=True)
    o = oms.submit("k", req, MKT, Book(position_qty=10), DAY0)
    log = oms.events[o.order_id]
    assert [(e.kind, e.state) for e in log] == [
        ("NEW", None),
        ("STATE", State.SUBMITTING),
        ("ATTEMPT", None),
        ("STATE", State.SUBMITTED),
    ]
    assert log[0].data == {
        "strategy_id": "s1",
        "instrument_id": 7,
        "side": "SELL",
        "qty": 4,
        "price": D("99.5"),
        "reduce_only": True,
    }
    assert all(e.ts == NOW for e in log) and [e.seq for e in log] == [0, 1, 2, 3]
    assert o.price == D("99.5") and replay(log) == o


def test_a_restart_rejects_what_was_never_decided_and_every_interrupted_order_is_handled_not_just_the_first():
    store = ListStore()
    oms, _ = build_with(store)
    for key in ("a", "b"):
        oms._emit(
            cid(key),
            None,
            "NEW",
            strategy_id="s1",
            instrument_id=7,
            side="BUY",
            qty=10,
            price=None,
            reduce_only=False,
        )
    again, _ = build_with(store)
    again.recover()
    assert [(again.orders[cid(k)].state, again.orders[cid(k)].reason) for k in ("a", "b")] == [
        (State.REJECTED, "interrupted before it was decided; nothing was sent")
    ] * 2


def test_a_restart_marks_an_attempted_send_unknown_with_the_reason_and_goes_on_to_the_next_order():
    store = ListStore()
    broker = FakeBroker()
    oms = Oms(broker, RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
    for key in ("a", "b"):
        oms._emit(
            cid(key),
            None,
            "NEW",
            strategy_id="s1",
            instrument_id=7,
            side="BUY",
            qty=10,
            price=None,
            reduce_only=False,
        )
        oms._emit(cid(key), State.SUBMITTING)
        oms._emit(cid(key), None, "ATTEMPT")
    again = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
    again.recover()
    for key in ("a", "b"):
        notes = [e for e in again.events[cid(key)] if e.state is State.UNKNOWN]
        assert [e.data["reason"] for e in notes] == ["the process stopped while it was being sent"]
        assert (
            again.orders[cid(key)].state is State.UNKNOWN
        )  # not found at the broker, so it stays unknown and escalates
    assert len(again.alerts) == 2


def test_a_restart_sends_the_logged_command_exactly_as_it_was_decided_including_reduce_only(
    monkeypatch,
):
    store = ListStore()
    oms = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
    oms._emit(
        cid(),
        None,
        "NEW",
        strategy_id="s1",
        instrument_id=7,
        side="SELL",
        qty=4,
        price=D("99.5"),
        reduce_only=True,
    )
    oms._emit(cid(), State.SUBMITTING)
    sent = []
    broker = FakeBroker()
    real = broker.place_order
    broker.place_order = lambda req, c: sent.append((req, c)) or real(req, c)
    switch = KillSwitch()
    again = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), store=store)
    switch.flatten(
        "s1", by="j", reason="fire", now=NOW, emergency_override=True
    )  # a reduce-only order is still allowed while flattening
    again.recover()
    assert sent == [(OrderRequest("s1", 7, Side.SELL, 4, D("99.5"), True), cid())]
    assert again.orders[cid()].state is State.SUBMITTED


def test_a_restart_does_not_send_a_command_the_kill_switch_now_forbids_and_says_why():
    for mode_call, word in (("pause", "PAUSE"), ("cancel", "CANCEL")):
        store = ListStore()
        oms = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
        oms._emit(
            cid(),
            None,
            "NEW",
            strategy_id="s1",
            instrument_id=7,
            side="BUY",
            qty=10,
            price=None,
            reduce_only=False,
        )
        oms._emit(cid(), State.SUBMITTING)
        broker, switch = FakeBroker(), KillSwitch()
        again = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), store=store)
        getattr(switch, mode_call)("s1", by="j", reason="r", now=NOW)
        again.recover()
        o = again.orders[cid()]
        assert (o.state, o.reason, broker.place_calls) == (
            State.REJECTED,
            f"the kill switch is {word}: not sent after the restart",
            0,
        )
    # a reduce-only order is refused in PAUSE too (only FLATTEN lets it through), and a plain order is refused in FLATTEN
    store = ListStore()
    oms = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
    oms._emit(
        cid(),
        None,
        "NEW",
        strategy_id="s1",
        instrument_id=7,
        side="SELL",
        qty=1,
        price=None,
        reduce_only=True,
    )
    oms._emit(cid(), State.SUBMITTING)
    broker, switch = FakeBroker(), KillSwitch()
    again = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), store=store)
    switch.pause("s1", by="j", reason="r", now=NOW)
    again.recover()
    assert again.orders[cid()].state is State.REJECTED and broker.place_calls == 0


def test_an_update_for_an_order_we_never_sent_is_kept_whole_and_a_plain_update_carries_no_reason():
    oms, broker, _ = build()
    stranger = BrokerOrder("B9", cid("never"), "COMPLETE", 1, D(5))
    assert oms.on_update(stranger) is None and oms.orphans == [stranger]
    o = submit(oms)
    oms.on_update(broker.move(o.order_id, "PARTIAL", 3, D(100)))
    update = [e for e in oms.events[o.order_id] if e.state is State.PARTIALLY_FILLED][0]
    assert update.data == {
        "filled_qty": 3,
        "avg_price": D(100),
        "broker_order_id": "B1",
    }  # no "reason" key when the broker gave none


def test_a_reason_the_broker_gives_is_logged_with_the_update():
    oms, broker, _ = build()
    o = submit(oms)
    oms.on_update(BrokerOrder("B1", o.order_id, "REJECTED", 0, None, "margin shortfall"))
    ev = [e for e in oms.events[o.order_id] if e.state is State.REJECTED][0]
    assert (
        ev.data["reason"] == "margin shortfall" and oms.orders[o.order_id].state is State.REJECTED
    )


def test_adopting_an_order_already_at_the_broker_records_all_of_it_and_then_follows_the_broker():
    oms, broker, _ = build()
    req = OrderRequest("s1", 7, Side.SELL, 4, D("99.5"), reduce_only=True)
    sent = BrokerOrder("B77", cid(), "PARTIAL", 2, D("99.6"))
    o = oms.adopt("k1", req, sent)
    assert (o.strategy_id, o.instrument_id, o.side, o.qty, o.price, o.broker_order_id) == (
        "s1",
        7,
        Side.SELL,
        4,
        D("99.5"),
        "B77",
    )
    assert (o.state, o.filled_qty, o.avg_price) == (
        State.PARTIALLY_FILLED,
        2,
        D("99.6"),
    ) and broker.place_calls == 0
    log = oms.events[o.order_id]
    assert log[0].kind == "NEW" and log[0].data == {
        "strategy_id": "s1",
        "instrument_id": 7,
        "side": "SELL",
        "qty": 4,
        "price": D("99.5"),
        "reduce_only": True,
    }
    assert [e.state for e in log if e.kind == "STATE"][:2] == [State.SUBMITTING, State.SUBMITTED]
    assert [e for e in log if e.state is State.SUBMITTED][0].data == {"broker_order_id": "B77"}
    assert (
        oms.adopt("k1", req, sent) is oms.orders[o.order_id]
    )  # again: the same order, nothing new


def test_an_unknown_order_that_cannot_be_found_is_noted_alerted_and_the_strategy_is_paused_at_that_moment():
    oms, broker, switch = build(script=["timeout_before"])
    o = submit(oms)
    assert (
        o.state is State.UNKNOWN and oms.alerts == []
    )  # sent, no answer: unknown, not yet looked up
    oms.resolve_unknown(o.order_id)
    assert any(
        e.kind == "NOTE" and e.data == {"text": "not found at the broker"}
        for e in oms.events[o.order_id]
    )
    assert oms.alerts == [
        f"order {o.order_id} is UNKNOWN (not found at the broker); s1 is now PAUSE"
    ]
    assert [(e.ts, e.scope, e.mode, e.by) for e in switch.events] == [
        (NOW, "s1", Mode.PAUSE, "policy:AMBIGUOUS_ORDER")
    ]
    broker.list_fails = True
    again = oms.resolve_unknown(o.order_id)
    assert any(
        e.kind == "NOTE" and e.data["text"] == "the lookup failed: timed out"
        for e in oms.events[again.order_id]
    )


def test_cancelling_asks_the_broker_for_the_right_order_logs_it_and_a_failed_cancel_does_not_stop_the_rest():
    oms, broker, _ = build()
    a, b = submit(oms, "a"), submit(oms, "b")
    assert sorted(oms.cancel_open("s1")) == sorted([a.order_id, b.order_id])
    assert sorted(broker.cancel_calls) == ["B1", "B2"]
    assert all(
        any(e.kind == "CANCEL_REQUESTED" and e.state is None for e in oms.events[x.order_id])
        for x in (a, b)
    )
    oms2, broker2, _ = build()
    c, d = submit(oms2, "c"), submit(oms2, "d")
    broker2.cancel_fails = True
    assert oms2.cancel_open("s1") == []
    for x in (c, d):  # both were tried: the first failure did not end the loop
        assert [e.data["text"] for e in oms2.events[x.order_id] if e.kind == "NOTE"] == [
            "cancel failed: timed out"
        ]


def test_a_partly_filled_sale_blocks_only_what_is_left_of_it_from_being_sold_again():
    broker, switch = FakeBroker(), KillSwitch()
    oms = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), own_positions_only=True)
    buy = oms.submit("b", OrderRequest("s1", 7, Side.BUY, 10), MKT, BOOK0, DAY0)
    oms.on_update(broker.move(buy.order_id, "COMPLETE", 10, D(100)))
    sale = oms.submit("s", OrderRequest("s1", 7, Side.SELL, 6), MKT, Book(position_qty=10), DAY0)
    oms.on_update(
        broker.move(sale.order_id, "PARTIAL", 2, D(101))
    )  # 2 sold, 4 still working; 8 held

    def again(k, q):
        return oms.submit(k, OrderRequest("s1", 7, Side.SELL, q), MKT, Book(position_qty=8), DAY0)

    assert again("t4", 4).state is State.SUBMITTED  # 8 held - 4 still selling = 4 may go
    assert again("t1", 1).state is State.REJECTED  # nothing is left to sell


def test_cancelling_an_open_order_the_broker_has_no_id_for_sends_the_empty_id_not_a_made_up_one():
    oms, broker, _ = build()
    oms._emit(
        cid("x"),
        None,
        "NEW",
        strategy_id="s1",
        instrument_id=7,
        side="BUY",
        qty=1,
        price=None,
        reduce_only=False,
    )
    oms._emit(cid("x"), State.SUBMITTING)
    oms._emit(cid("x"), State.SUBMITTED)  # open, but no broker id was ever recorded
    assert oms.cancel_open("s1") == [cid("x")] and broker.cancel_calls == [""]


def test_reconciliation_says_exactly_what_differs_and_logs_it_on_the_order():
    oms, broker, switch = build()
    drifted, filled, lost = submit(oms, "b"), submit(oms, "c"), submit(oms, "d")
    refused = oms.submit(
        "r", REQ, MKT, BOOK0, Day(orders=0)
    )  # approved, so it is at the broker too: make a REJECTED one instead
    refused_id = cid("rej")
    oms._emit(
        refused_id,
        None,
        "NEW",
        strategy_id="s1",
        instrument_id=7,
        side="BUY",
        qty=1,
        price=None,
        reduce_only=False,
    )
    oms._emit(
        refused_id, State.REJECTED, reason="risk: x"
    )  # never reached the broker: not a mismatch
    broker.move(drifted.order_id, "CANCELLED")
    broker.move(filled.order_id, "OPEN", 3, D(100))
    del broker.book[lost.order_id]
    orphan = "A" + "0" * 19  # a tag the platform could have made, for an order the OMS never sent
    broker.book[orphan] = BrokerOrder("B99", orphan, "OPEN")
    broker.book["manual-1"] = BrokerOrder("B98", "manual-1", "OPEN")  # placed by hand: not ours
    found = oms.reconcile(threshold=99)
    got = {(m.kind, m.client_order_id): m.detail for m in found}
    assert got == {
        ("STATE_MISMATCH", drifted.order_id): "the OMS has SUBMITTED, the broker CANCELLED",
        ("FILL_MISMATCH", filled.order_id): "the OMS filled 0, the broker 3",
        (
            "MISSING_AT_BROKER",
            lost.order_id,
        ): "the OMS has it SUBMITTED, the broker does not know it",
        ("ORPHAN", orphan): "the broker has an order the OMS never sent",
    }
    assert refused.order_id not in {m.client_order_id for m in found} and refused_id not in {
        m.client_order_id for m in found
    }
    logged = [e for e in oms.events[drifted.order_id] if e.kind == "RECONCILED"]
    assert [e.data for e in logged] == [
        {"result": "STATE_MISMATCH", "detail": "the OMS has SUBMITTED, the broker CANCELLED"}
    ]
    assert orphan not in oms.events  # an order the OMS does not have gets no log
    assert switch.events == [] and oms.alerts == []  # four differences, threshold 99: no halt


def test_reconciliation_at_its_threshold_halts_by_policy_at_that_moment_and_names_every_kind():
    oms, broker, switch = build()
    a, b = submit(oms, "a"), submit(oms, "b")
    del broker.book[a.order_id]
    broker.move(b.order_id, "CANCELLED")
    found = oms.reconcile(threshold=2)
    assert len(found) == 2
    assert [(e.ts, e.scope, e.mode, e.by) for e in switch.events] == [
        (NOW, None, Mode.PAUSE, "policy:RECONCILIATION")
    ]
    assert oms.alerts == ["reconciliation found 2 mismatch(es): MISSING_AT_BROKER; STATE_MISMATCH"]
    oms2, _, switch2 = build()
    submit(oms2, "a")
    assert (
        oms2.reconcile(threshold=2) == [] and switch2.events == []
    )  # one fewer than the threshold would not halt either


def test_an_unreachable_broker_is_one_mismatch_with_the_error_and_halts_at_that_moment():
    oms, broker, switch = build()
    broker.list_fails = True
    assert oms.reconcile() == [Mismatch("BROKER_UNREACHABLE", "", "timed out")]
    assert [(e.ts, e.scope, e.mode, e.by) for e in switch.events] == [
        (NOW, None, Mode.PAUSE, "policy:BROKER_DOWN")
    ]
    assert oms.alerts == ["reconciliation could not read the broker: timed out"]


def test_a_rejected_order_listed_first_does_not_hide_a_mismatch_in_the_orders_after_it():
    oms, broker, _ = build()
    gone = cid("rej")
    oms._emit(
        gone,
        None,
        "NEW",
        strategy_id="s1",
        instrument_id=7,
        side="BUY",
        qty=1,
        price=None,
        reduce_only=False,
    )
    oms._emit(gone, State.REJECTED, reason="risk: x")  # first in the log, never reached the broker
    later = submit(oms, "later")
    broker.move(later.order_id, "CANCELLED")
    assert [m.kind for m in oms.reconcile(threshold=99)] == ["STATE_MISMATCH"]


def test_a_logged_command_without_a_reduce_only_flag_is_not_reduce_only_when_the_restart_decides_whether_to_send_it():
    store = ListStore()
    oms = Oms(FakeBroker(), RiskEngine(Limits(), KillSwitch()), SimClock(NOW), store=store)
    oms._emit(
        cid(), None, "NEW", strategy_id="s1", instrument_id=7, side="SELL", qty=1, price=None
    )  # an older log: no flag
    oms._emit(cid(), State.SUBMITTING)
    broker, switch = FakeBroker(), KillSwitch()
    again = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW), store=store)
    switch.flatten(
        "s1", by="j", reason="fire", now=NOW, emergency_override=True
    )  # only a reduce-only order may go during FLATTEN
    again.recover()
    assert again.orders[cid()].state is State.REJECTED and broker.place_calls == 0

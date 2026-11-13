"""A screener used as a strategy, on a synthetic market. ENGINEERING_TEST_ONLY: nothing here is a strategy result."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.strategies.screener import ScreenerParams, ScreenerStrategy, ScreenSpec
from algo.strategy.context import Context, PortfolioView
from tests.unit.strategies.test_nifty200_momentum import LAST, Stub
from tests.unit.strategies.test_trend_pullback import ctx_with, members, uptrend


def screen(**over) -> ScreenSpec:
    base = {"conditions": [{"field": "chg_3m", "op": "gt", "value": 0}], "sort": "chg_3m"}
    return ScreenSpec.model_validate({**base, **over})


def run(closes, spec=None, slots=10, day=LAST, held=(), universe=None):
    s = ScreenerStrategy(
        ScreenerParams(max_positions=slots), members(list(universe or closes)), spec or screen()
    )
    return s, s.on_schedule(ctx_with(Stub(closes), day, held=held))


def kept(closes, iid, qty=10, equity=100000):
    """The weight a held stock is returned at: what it is worth now over the account (so it is not traded)."""
    return (D(qty) * closes[iid][LAST] / D(equity)).quantize(D("1e-12"), rounding="ROUND_UP")


def big(closes, positions, equity=D(100000), day=LAST):
    """A context holding `positions` (iid -> shares) in an account worth `equity`."""
    stub = Stub(closes)
    clock = SimClock(datetime.combine(day, time(12, 0), UTC))
    stub.clock = clock
    return Context(clock, stub, PortfolioView.of(D(100), positions, equity), "research")  # type: ignore[arg-type]


def test_the_matches_are_held_equal_weight_and_a_falling_stock_never_matches():
    closes = {1: uptrend("0.001"), 2: uptrend("0.003"), 3: uptrend("0.002"), 4: uptrend("-0.001")}
    _, t = run(closes, slots=5)
    assert t == {i: D("0.2") for i in (1, 2, 3)}


def test_only_the_best_few_are_kept_when_more_match_than_there_are_slots():
    closes = {i: uptrend(f"0.00{i}") for i in range(1, 8)}
    assert set(run(closes, slots=5)[1]) == {3, 4, 5, 6, 7}  # the five steepest risers
    assert set(run(closes, spec=screen(descending=False), slots=5)[1]) == {1, 2, 3, 4, 5}


def test_it_checks_every_session_there_is_no_once_a_month_memory():
    closes = {1: uptrend()}
    s, first = run(closes)
    assert first == {1: D("0.1")}
    assert run(closes)[1] == first  # a fresh run on the same data decides the same
    assert s.on_schedule(ctx_with(Stub(closes), LAST)) == first  # and so does the same run, again


def test_nothing_matching_and_nothing_held_is_no_change():
    spec = screen(conditions=[{"field": "chg_1y", "op": "gt", "value": 10_000}])
    assert run({1: uptrend()}, spec=spec)[1] is None


def test_a_stock_that_starts_matching_is_bought_while_others_are_held():
    closes = {1: uptrend("0.002"), 2: uptrend("0.003")}
    _, t = run(closes, held=[1])
    assert t == {
        1: kept(closes, 1),
        2: D("0.1"),
    }  # the held one is left at its own size, the new match gets a slot


def test_a_held_stock_that_stops_matching_is_sold_the_same_session():
    closes = {
        1: uptrend("0.002"),
        2: uptrend("-0.001"),
    }  # 2 is falling: its 3-month change is below zero
    s, t = run(closes, held=[1, 2])
    assert t == {
        1: kept(closes, 1)
    }  # the other is dropped; the one that still matches is not resized
    assert s.audit[-1]["exits"] == {2: "no longer matches the screen"}


def test_nothing_changes_while_every_held_stock_still_matches_and_nothing_else_does():
    closes = {1: uptrend("0.002"), 2: uptrend("0.003")}
    assert run(closes, held=[1, 2])[1] is None


def test_a_freed_slot_is_filled_by_the_next_best_match():
    closes = {i: uptrend(f"0.00{i}") for i in range(1, 8)} | {9: uptrend("-0.001")}
    held = {
        i: D("0.15") * D(100000) / closes[i][LAST] for i in (3, 4, 5, 6, 9)
    }  # five slots of 15% each
    s = ScreenerStrategy(ScreenerParams(max_positions=5), members(list(closes)), screen())
    t = s.on_schedule(big(closes, held))  # 9 stopped matching; 7 is the best match not held
    assert t is not None and set(t) == {3, 4, 5, 6, 7} and t[7] == D("0.2")
    assert t[3] == weight_of(closes, 3, held[3]).quantize(D("1e-12"), rounding="ROUND_UP")


def test_a_held_stock_with_no_bar_today_is_kept_because_it_cannot_be_traded():
    closes = {1: uptrend("0.002")}
    assert run(closes, held=[1, 9])[1] is None  # 9 has no bar, so it stays held and nothing changes


def test_a_day_with_no_data_decides_nothing():
    assert run({1: uptrend()}, day=LAST + timedelta(days=40))[1] is None


def test_holding_more_than_the_slots_keeps_the_best_ranked():
    closes = {i: uptrend(f"0.00{i}") for i in range(1, 8)}
    _, t = run(closes, slots=5, held=[1, 2, 3, 4, 5, 6, 7])
    assert set(t) == {3, 4, 5, 6, 7}  # the two weakest matches are sold


def test_the_strategy_version_moved_when_it_became_a_daily_rule():
    assert ScreenerStrategy.version == "3"


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"conditions": [{"field": "segment", "op": "eq", "value": "large"}]}, "segment"),
        ({"sort": "segment"}, "segment"),
        ({"conditions": [{"field": "nope", "op": "gt", "value": 1}]}, "nope"),
        (
            {"conditions": [{"field": "rsi_14", "op": "between", "value": [9, 1]}]},
            "low is above high",
        ),
    ],
)
def test_a_screen_that_cannot_be_backtested_is_refused_with_the_reason(over, why):
    assert why in (screen(**over).problem() or "")


def test_a_price_only_screen_has_no_problem():
    assert screen().problem() is None


def weight_of(closes, iid, shares, equity=D(100000)):
    return shares * closes[iid][LAST] / equity


def test_winners_that_have_outgrown_a_slot_leave_new_entries_only_the_room_that_is_left():
    closes = {1: uptrend("0.002"), 2: uptrend("0.003")}
    shares = D("0.95") * D(100000) / closes[1][LAST]  # stock 1 is already 95% of the account
    s = ScreenerStrategy(ScreenerParams(max_positions=10), members([1, 2]), screen())
    t = s.on_schedule(big(closes, {1: shares}))
    assert t is not None and set(t) == {1, 2}
    assert t[2] <= D("0.0500001") and sum(t.values()) <= 1 + D(
        "1e-9"
    )  # never more than the whole account


def test_a_full_account_has_no_room_so_a_new_match_is_not_proposed():
    closes = {1: uptrend("0.002"), 2: uptrend("0.003")}
    shares = D(100000) / closes[1][LAST]  # stock 1 is the whole account
    s = ScreenerStrategy(ScreenerParams(max_positions=10), members([1, 2]), screen())
    assert s.on_schedule(big(closes, {1: shares})) is None


def test_a_fully_invested_account_of_many_stocks_never_adds_up_to_more_than_it_is_worth():
    closes = {i: uptrend(f"0.00{i}") for i in range(1, 6)}
    held = {i: D(100000) / 5 / closes[i][LAST] for i in range(1, 6)}  # five equal slots, all of it
    s = ScreenerStrategy(ScreenerParams(max_positions=5), members(list(closes)), screen())
    assert s.on_schedule(big(closes, held)) is None  # nothing entered or left
    closes[6] = uptrend("-0.001")
    held[6] = D(0)
    held = {i: q for i, q in held.items() if q}
    sold = ScreenerStrategy(ScreenerParams(max_positions=5), members(list(closes)), screen())
    t = sold.on_schedule(big(closes | {2: uptrend("-0.001")}, held))  # stock 2 stops matching
    assert t is not None and 2 not in t and sum(t.values()) <= 1 + D("1e-9")

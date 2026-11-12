"""Trend-filtered RSI pullback on a synthetic market. ENGINEERING_TEST_ONLY: nothing here is a
strategy experiment and none of it may enter the validation registry."""

from datetime import UTC, date, datetime, time
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from algo.strategy.context import Context, PortfolioView
from tests.unit.strategies.test_nifty200_momentum import DAYS, LAST, Stub

P = TrendPullbackParams()  # trend 200, enter below RSI 25, exit above RSI 60, 10 positions


def members(ids, start=date(2000, 1, 1)) -> IntervalMembership:
    return IntervalMembership([Interval(i, start, None) for i in ids])


def ctx_with(stub: Stub, day: date, held=(), mode: str = "research") -> Context:
    clock = SimClock(datetime.combine(day, time(12, 0), UTC))
    stub.clock = clock
    positions = {i: D(10) for i in held}
    return Context(clock, stub, PortfolioView.of(D(100000), positions, D(100000)), mode)  # type: ignore[arg-type]


def uptrend(slope="0.002", dip_days=0, dip="-0.02") -> dict[date, D]:
    """Rises smoothly, then falls `dip_days` sessions in a row ending on the last day."""
    p, out = D(100), {}
    for i, d in enumerate(DAYS):
        out[d] = p
        p *= 1 + D(dip if i >= len(DAYS) - 1 - dip_days else slope)
    return out


def broken() -> dict[date, D]:
    """Rose, then fell for long enough to end below its 200-day average, oversold at the end."""
    p, out = D(100), {}
    for i, d in enumerate(DAYS):
        out[d] = p
        p *= 1 + D("0.003" if i < 350 else "-0.006")
    return out


def run(ids, closes, held=(), params=P, mem=None, day=LAST):
    s = TrendPullback(params, mem or members(ids))
    return s, s.on_schedule(ctx_with(Stub(closes), day, held))


def test_params_are_the_small_registered_grid_only():
    for bad in (dict(trend_sma=50), dict(entry_rsi=35), dict(exit_rsi=50), dict(max_positions=15)):
        with pytest.raises(ValueError):
            TrendPullbackParams(**bad)
    assert P.model_dump() == {
        "trend_sma": 200,
        "entry_rsi": 25,
        "exit_rsi": 60,
        "max_positions": 10,
    }


def test_universe_is_every_instrument_ever_a_member_and_it_decides_every_session():
    s = TrendPullback(P, members([3, 1, 2]))
    assert s.universe(None) == [1, 2, 3]  # type: ignore[arg-type]
    assert (s.id, s.version) == ("trend_pullback", "1")
    assert s.requirements().lookback_days >= 300


def test_an_oversold_stock_in_an_uptrend_is_bought_and_the_rest_stay_out():
    closes = {1: uptrend(dip_days=6), 2: uptrend(), 3: broken()}
    s, t = run([1, 2, 3], closes)
    assert t == {1: D("0.1")}  # 2 is not oversold; 3 is oversold but below its 200-day average
    row = s.audit[-1]
    assert row["entries"] == [1] and row["exits"] == {} and row["ready"] == 3


def test_a_stock_is_held_while_it_stays_between_the_entry_and_exit_levels():
    s, t = run([1], {1: uptrend(dip_days=6)}, held=[1])
    assert t == {1: D("0.1")} and s.audit[-1]["entries"] == []


def test_a_held_stock_that_has_recovered_is_sold_and_one_that_lost_its_trend_is_sold():
    closes = {1: uptrend(), 2: broken(), 3: uptrend(dip_days=6)}
    s, t = run([1, 2, 3], closes, held=[1, 2, 3])
    assert set(t) == {3}
    assert s.audit[-1]["exits"] == {1: "rsi_above_exit", 2: "below_trend"}


def test_a_held_stock_that_left_the_index_is_sold_even_if_it_still_looks_fine():
    mem = IntervalMembership(
        [Interval(1, date(2000, 1, 1), LAST), Interval(2, date(2000, 1, 1), None)]
    )
    s, t = run([1, 2], {1: uptrend(dip_days=6), 2: uptrend()}, held=[1], mem=mem)
    assert t == {}
    assert s.audit[-1]["exits"] == {1: "left_universe"}


def test_with_more_candidates_than_slots_the_most_oversold_win_and_held_names_use_slots():
    ids = list(range(1, 16))
    closes = {
        i: uptrend(dip_days=4, dip=str(-(0.010 + 0.001 * i))) for i in ids
    }  # a deeper fall leaves a lower RSI
    _, t = run(ids, closes)
    assert set(t) == set(range(6, 16)) and all(w == D("0.1") for w in t.values())
    _, t = run(ids, closes, held=[1, 2, 3, 4, 5, 6, 7, 8])
    assert set(t) == {1, 2, 3, 4, 5, 6, 7, 8, 15, 14}  # eight kept, two most oversold added


def test_never_holds_more_than_the_limit_even_when_a_sale_has_not_finished_yet():
    """A position being sold down in pieces (orders split by size or volume) is still held the next day; its slot may already
    have been given to a new stock. The targets must still fit in 100%: the one closest to its exit goes."""
    five = TrendPullbackParams(max_positions=5)
    ids = list(range(1, 7))
    closes = {
        i: uptrend(dip_days=4, dip=str(-(0.010 + 0.001 * i))) for i in ids
    }  # a higher id is more oversold
    s, t = run(ids, closes, held=ids, params=five)
    assert set(t) == {2, 3, 4, 5, 6} and sum(t.values()) <= 1
    assert s.audit[-1]["exits"] == {1: "over_limit"}
    stale = {d: c for d, c in uptrend(dip_days=6).items() if d != LAST}
    filler = {
        i: uptrend() for i in range(100, 130)
    }  # steady and never oversold: lets one missing bar be tolerated
    s, t = run(
        ids + [99, *filler], {**closes, **filler, 99: stale}, held=ids + [99], params=five
    )  # 99 has no bar today: it cannot be sold, so it keeps its slot
    assert 99 in t and len(t) == 5 and sum(t.values()) <= 1
    assert set(s.audit[-1]["exits"].values()) == {"over_limit"} and len(s.audit[-1]["exits"]) == 2


def test_a_stock_held_exactly_at_the_limit_is_not_touched():
    five = TrendPullbackParams(max_positions=5)
    ids = list(range(1, 6))
    s, t = run(
        ids,
        {i: uptrend(dip_days=4, dip=str(-(0.010 + 0.001 * i))) for i in ids},
        held=ids,
        params=five,
    )
    assert set(t) == set(ids) and s.audit[-1]["exits"] == {}


def test_a_held_stock_with_no_bar_today_is_kept_and_one_not_held_cannot_be_bought():
    stale = {d: c for d, c in uptrend(dip_days=6).items() if d != LAST}
    ids = list(range(1, 25)) + [99]
    base = {i: uptrend() for i in range(1, 25)}
    _, t = run(ids, {**base, 99: stale}, held=[99])
    assert 99 in t
    s, t = run(ids, {**base, 99: stale})
    assert 99 not in t and s.audit[-1]["not_ready"] == [99]


def test_short_history_is_reported_not_traded_and_too_many_unready_names_stop_the_run():
    young = {d: c for d, c in uptrend(dip_days=6).items() if d > DAYS[-100]}
    ids = list(range(1, 40)) + [50]
    s, t = run(ids, {**{i: uptrend() for i in range(1, 40)}, 50: young})
    assert 50 not in t and s.audit[-1]["not_ready"] == [50]  # 1 of 40 members: tolerated
    two_young = {**{i: uptrend() for i in range(1, 11)}, 50: young, 51: young}
    with pytest.raises(DataNotReady, match="unready"):
        run(list(range(1, 11)) + [50, 51], two_young)
    with pytest.raises(DataNotReady, match="no members"):
        run([], {})


def test_strict_mode_makes_no_decision_when_the_membership_evidence_is_unusable():
    mem = IntervalMembership([Interval(1, date(2000, 1, 1), None)], unusable={LAST: "unpublished"})
    s = TrendPullback(P, mem)
    stub = Stub({1: uptrend(dip_days=6)})
    assert s.on_schedule(ctx_with(stub, LAST, mode="strict")) is None
    assert s.audit[-1]["skipped"].startswith("strict") and s.audit[-1]["reasons"] == "unpublished"
    assert s.on_schedule(ctx_with(stub, LAST, mode="research")) == {1: D("0.1")}


def test_the_indicators_of_the_same_bars_are_computed_once_and_a_changed_bar_is_computed_again(
    monkeypatch,
):
    from algo.indicators import catalog
    from algo.strategies import trend_pullback as tp

    closes = list(uptrend().values())
    from datetime import UTC, datetime, time

    from algo.data.reader import AdjBar

    def make(vals):
        return [
            AdjBar(datetime.combine(d, time(3, 45), UTC), c, c, c, c, D(1), D(1), 5)
            for d, c in zip(uptrend(), vals, strict=True)
        ]

    calls = []
    real = catalog.compute
    monkeypatch.setattr(catalog, "compute", lambda *a, **k: calls.append(1) or real(*a, **k))
    tp.clear_indicator_cache()
    first = tp._indicators(make(closes), 200)
    assert (
        tp._indicators(make(closes), 200) == first and len(calls) == 1
    )  # the second call is served from the memo
    changed = list(closes)
    changed[-1] = changed[-1] + 1
    assert (
        tp._indicators(make(changed), 200) != first and len(calls) == 2
    )  # a different last close is a different question
    tp.clear_indicator_cache()
    tp._indicators(make(closes), 200)
    assert len(calls) == 3  # cleared: computed again
    assert (
        tp._indicators(make(closes)[:50], 200) is None
    )  # too little history never reaches the memo


def test_a_full_memo_is_emptied_rather_than_growing_without_limit(monkeypatch):
    from datetime import UTC, datetime, time

    from algo.data.reader import AdjBar
    from algo.strategies import trend_pullback as tp

    monkeypatch.setattr(tp, "_CACHE_MAX", 1)
    tp.clear_indicator_cache()
    bars = [
        AdjBar(datetime.combine(d, time(3, 45), UTC), c, c, c, c, D(1), D(1), 5)
        for d, c in uptrend().items()
    ]
    tp._indicators(bars, 100)
    tp._indicators(bars, 200)  # the memo is full at one entry: it empties before storing this one
    assert len(tp._CACHE) == 1


def test_the_history_a_stock_needs_before_it_can_be_decided_on_is_the_trend_average_plus_the_warm_up():
    assert TrendPullback.required_history({"trend_sma": 200, "entry_rsi": 25}) == 210
    assert TrendPullback.required_history({"trend_sma": 100}) == 110


def test_a_membership_knows_its_first_day():
    assert members([1, 2], start=date(2024, 3, 1)).first_day() == date(2024, 3, 1)
    assert IntervalMembership([]).first_day() is None

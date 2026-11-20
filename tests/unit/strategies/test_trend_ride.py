"""trend_ride on synthetic markets. ENGINEERING_TEST_ONLY: nothing here is a strategy experiment and none of it may enter the validation registry."""

from datetime import date
from decimal import Decimal as D

import pytest

from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategies.registry import STRATEGIES
from algo.strategies.trend_ride import TrendRide, TrendRideParams, reading
from tests.unit.strategies.test_ema_macd_cross import bars_to
from tests.unit.strategies.test_nifty200_momentum import DAYS, LAST, Stub
from tests.unit.strategies.test_trend_pullback import ctx_with, members

P = TrendRideParams()
N = len(DAYS)


def series(fn) -> dict[date, D]:
    return {d: D(str(round(fn(i), 4))) for i, d in enumerate(DAYS)}


def chop(i):  # sideways with a little noise so ATR is not zero
    return 100 + (i % 2)


def breakout(
    i,
):  # chop, then 20 sessions of +1% a day: the last day is a fresh 20-day high inside an uptrend
    return chop(i) if i < N - 20 else 101 * 1.01 ** (i - (N - 20))


def breakout_then_drop(i):  # the same, but the last day falls 8%
    return breakout(i) * (0.92 if i == N - 1 else 1)


def grind_down(i):  # a slow decline with noise: below its EMA50 long before any ATR stop is touched
    return 100 * 0.999**i + (i % 2)


def run(ids, closes, held=(), params=P, day=LAST):
    s = TrendRide(params, members(ids))
    return s, s.on_schedule(ctx_with(Stub(closes), day, held))


def test_params_registry_and_history_need():
    for bad in (dict(breakout=30), dict(atr_mult=5), dict(max_positions=15)):
        with pytest.raises(ValueError):
            TrendRideParams(**bad)
    assert STRATEGIES["trend_ride"] == (TrendRide, TrendRideParams)
    s = TrendRide(P, members([2, 1]))
    assert s.universe(None) == [1, 2] and (s.id, s.version) == ("trend_ride", "1")  # type: ignore[arg-type]
    assert (
        TrendRide.required_history({"breakout": 55}) >= 80 and s.requirements().lookback_days >= 135
    )


def test_state_names_where_the_trend_is():
    def r(fn):
        return reading(bars_to(series(fn), LAST)[-150:], 20, 3)

    assert r(breakout).state == "UP" and r(breakout).new_high
    assert r(grind_down).state == "DOWN" and not r(grind_down).new_high
    assert r(chop).state == "RANGE"
    assert reading(bars_to(series(chop), DAYS[30]), 20, 3) is None  # too little history


def test_a_new_high_inside_an_uptrend_is_bought_and_chop_or_a_downtrend_is_not():
    s, t = run([1, 2, 3], {1: series(breakout), 2: series(chop), 3: series(grind_down)})
    assert t == {1: D("0.1")} and s.audit[-1]["entries"] == [1]
    assert s.audit[-1]["states"] == {"UP": 1, "DOWN": 1, "RANGE": 1}


def test_a_held_uptrend_is_kept_with_its_stop_reported():
    s, t = run([1], {1: series(breakout)}, held=[1])
    assert set(t) == {1} and s.audit[-1]["exits"] == {} and 1 in s.audit[-1]["stops"]


def test_a_close_under_the_trailing_stop_exits():
    s, t = run([1], {1: series(breakout_then_drop)}, held=[1])
    assert t == {} and s.audit[-1]["exits"] == {1: "stop_hit"}


def test_losing_the_ema50_exits_even_when_the_stop_is_not_touched():
    s, t = run([1], {1: series(grind_down)}, held=[1], params=TrendRideParams(atr_mult=4))
    assert t == {} and s.audit[-1]["exits"] == {1: "trend_lost"}


def test_left_universe_no_bar_and_over_the_limit():
    ids = list(range(1, 22))  # 21 members: one unready is under the 5% limit
    closes = {i: series(breakout) for i in ids}
    closes[2] = {d: c for d, c in closes[2].items() if d < LAST}  # no bar today
    closes[99] = series(breakout)  # held, not a member
    s, t = run(ids, closes, held=[1, 2, 99])
    assert {1, 2} <= set(t) and s.audit[-1]["exits"] == {99: "left_universe"}
    assert s.audit[-1]["not_ready"] == [2]
    small = TrendRideParams(max_positions=5)
    ids = list(range(1, 8))
    s, t = run(ids, {i: series(breakout) for i in ids}, held=ids, params=small)
    assert len(t) == 5 and sum(v == "over_limit" for v in s.audit[-1]["exits"].values()) == 2


def test_unready_members_and_empty_universe_stop_the_run():
    short = {d: c for d, c in series(chop).items() if d < DAYS[40]}
    with pytest.raises(DataNotReady):
        run([1, 2], {1: series(breakout), 2: short})
    with pytest.raises(DataNotReady):
        run([], {})


def test_strict_mode_skips_when_membership_evidence_is_unusable():
    class Bad(IntervalMembership):
        def unusable_reason(self, day):
            return "unpublished"

    s = TrendRide(P, Bad([Interval(1, date(2000, 1, 1), None)]))
    assert s.on_schedule(ctx_with(Stub({1: series(chop)}), LAST, mode="strict")) is None
    assert s.audit[-1]["skipped"].startswith("strict")

"""EMA 9/21 + MACD cross strategy on a synthetic market. ENGINEERING_TEST_ONLY: nothing here is a strategy experiment and none of it may enter the validation registry."""

import math
from datetime import UTC, date, datetime, time
from decimal import Decimal as D

import pytest

from algo.data.reader import AdjBar
from algo.data.universe import Interval
from algo.strategies.ema_macd_cross import EmaMacdCross, EmaMacdCrossParams, _state
from algo.strategies.nifty200_momentum import DataNotReady, IntervalMembership
from algo.strategies.registry import STRATEGIES
from tests.unit.strategies.test_nifty200_momentum import DAYS, LAST
from tests.unit.strategies.test_trend_pullback import ctx_with, members

P = EmaMacdCrossParams()


def wave() -> dict[date, D]:
    """Repeating 30-session cycles: 22 of accelerating decline, then 8 sharp rises, so MACD and EMA 9/21 cross back up together again and again."""
    out, lp = {}, 0.0
    for i, d in enumerate(DAYS):
        ph = (i % 30) / 30
        lp += -0.003 * (1 + ph * 2) if ph < 0.75 else 0.02
        out[d] = D(str(round(100 * math.exp(lp), 4)))
    return out


def uptrend() -> dict[date, D]:
    p, out = D(100), {}
    for d in DAYS:
        out[d] = p
        p *= D("1.004")
    return out


def bars_to(closes: dict[date, D], day: date) -> list[AdjBar]:
    return [
        AdjBar(datetime.combine(d, time(3, 45), UTC), c, c, c, c, D(1000), D(1))
        for d, c in sorted(closes.items())
        if d <= day
    ]


def first_day(closes, want) -> date:
    return next(d for d in DAYS[100:] if want(_state(bars_to(closes, d)[-140:], 3)))


def run(ids, closes, day, held=(), params=P):
    from tests.unit.strategies.test_nifty200_momentum import Stub

    s = EmaMacdCross(params, members(ids))
    return s, s.on_schedule(ctx_with(Stub(closes), day, held))


def test_params_registry_and_history_need():
    for bad in (dict(cross_window=4), dict(max_positions=15)):
        with pytest.raises(ValueError):
            EmaMacdCrossParams(**bad)
    assert STRATEGIES["ema_macd_cross"] == (EmaMacdCross, EmaMacdCrossParams)
    s = EmaMacdCross(P, members([2, 1]))
    assert s.universe(None) == [1, 2] and (s.id, s.version) == ("ema_macd_cross", "1")  # type: ignore[arg-type]
    assert EmaMacdCross.required_history({}) == 60 and s.requirements().lookback_days >= 135


def test_short_history_is_not_ready():
    assert _state(bars_to(uptrend(), DAYS[30]), 3) is None


def test_a_fresh_turn_is_bought_and_an_old_uptrend_is_not():
    closes = {1: wave(), 2: uptrend()}
    day = first_day(closes[1], lambda st: st is not None and st[0] and st[1])
    s, t = run([1, 2], closes, day)
    assert t == {1: D("0.1")}  # 2 is up on both but crossed long ago
    assert s.audit[-1]["entries"] == [1] and s.audit[-1]["ready"] == 2


def test_a_held_stock_stays_while_both_are_up_and_is_sold_when_either_turns_down():
    closes = {1: wave(), 2: uptrend()}
    up_day = first_day(closes[1], lambda st: st is not None and st[0])
    _, t = run([1, 2], closes, up_day, held=[1, 2])
    assert set(t) == {1, 2}
    down_day = first_day(closes[1], lambda st: st is not None and not st[0])
    s, t = run([1, 2], closes, down_day, held=[1, 2])
    assert set(t) == {2} and s.audit[-1]["exits"] == {1: "macd_or_ema_turned_down"}


def test_a_stock_that_left_the_universe_is_sold_and_one_without_a_bar_is_kept():
    from tests.unit.strategies.test_nifty200_momentum import Stub

    ids = list(range(1, 22))  # 21 members: one unready is under the 5% limit
    closes = {i: uptrend() for i in ids}
    closes[2] = {d: c for d, c in uptrend().items() if d < LAST}  # no bar today
    closes[99] = uptrend()  # held but not a member
    st = EmaMacdCross(P, members(ids))
    t = st.on_schedule(ctx_with(Stub(closes), LAST, held=[1, 2, 99]))
    assert set(t) == {1, 2}
    assert st.audit[-1]["exits"] == {99: "left_universe"} and st.audit[-1]["not_ready"] == [2]


def test_over_the_limit_the_weakest_are_dropped_and_unready_members_stop_the_run():
    small = EmaMacdCrossParams(max_positions=5)
    ids = list(range(1, 8))
    closes = {i: uptrend() for i in ids}
    s, t = run(ids, closes, LAST, held=ids, params=small)
    assert len(t) == 5 and sum(1 for v in s.audit[-1]["exits"].values() if v == "over_limit") == 2
    with pytest.raises(DataNotReady):
        run([1, 2], {1: uptrend(), 2: {d: c for d, c in uptrend().items() if d < DAYS[40]}}, LAST)
    with pytest.raises(DataNotReady):
        run([], {}, LAST)


def test_strict_mode_skips_when_membership_evidence_is_unusable():
    class Bad(IntervalMembership):
        def unusable_reason(self, day):
            return "unpublished"

    from tests.unit.strategies.test_nifty200_momentum import Stub

    s = EmaMacdCross(P, Bad([Interval(1, date(2000, 1, 1), None)]))
    assert s.on_schedule(ctx_with(Stub({1: uptrend()}), LAST, mode="strict")) is None
    assert s.audit[-1]["skipped"].startswith("strict")

"""Trend-filtered 12-1 momentum on a synthetic market. ENGINEERING_TEST_ONLY: nothing here is a
strategy experiment and none of it may enter the validation registry."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.data.reader import AdjBar
from algo.data.universe import Interval
from algo.strategies.nifty200_momentum import (
    DataNotReady,
    IntervalMembership,
    MomentumParams,
    Nifty200TrendMomentum,
    PlainMomentum,
    PlainParams,
)
from algo.strategy.context import Context, PortfolioView


def sessions(n: int, start: date = date(2018, 1, 1)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions(700)
LAST = DAYS[-1]


class Stub:
    """Stands in for DataAccess: bars up to now, oldest first, window by calendar days."""

    def __init__(self, closes: dict[int, dict[date, D]]) -> None:
        self.closes, self.clock = closes, None

    def history(self, ids, lookback_days, *, adjusted=True):
        now = self.clock.now().date()
        lo = now - timedelta(days=lookback_days)
        return {
            i: [
                AdjBar(datetime.combine(d, time(3, 45), UTC), c, c, c, c, D(1000), D(1))
                for d, c in sorted(self.closes[i].items())
                if lo < d <= now
            ]
            for i in ids
            if i in self.closes
        }


def trend(slope: str, start: str = "100") -> dict[date, D]:
    """price_t = start * (1 + slope)^t : a smooth up (slope>0) or down trend."""
    p, out = D(start), {}
    for d in DAYS:
        out[d] = p
        p = p * (1 + D(slope))
    return out


def ctx_for(stub: Stub, day: date) -> Context:
    clock = SimClock(datetime.combine(day, time(12, 0), UTC))
    stub.clock = clock
    return Context(clock, stub, PortfolioView.of(D(100000), {}, D(100000)), "research")  # type: ignore[arg-type]


def members(ids, start=date(2000, 1, 1)) -> IntervalMembership:
    return IntervalMembership([Interval(i, start, None) for i in ids])


P = MomentumParams(lookback=126, trend_sma=100, holdings=20)


def strat(ids, params=P):
    return Nifty200TrendMomentum(params, members(ids)), None


def run(ids, closes, day=LAST, params=P):
    s = Nifty200TrendMomentum(params, members(ids))
    return s, s.on_schedule(ctx_for(Stub(closes), day))


def market(n_up=30, n_down=10):
    up = {i: trend(str(0.0005 + i * 0.00002)) for i in range(1, n_up + 1)}
    down = {100 + i: trend("-0.0004") for i in range(n_down)}
    return {**up, **down}


def test_params_are_the_registered_grid_only():
    for bad in (dict(lookback=100), dict(trend_sma=50), dict(holdings=25)):
        with pytest.raises(ValueError):
            MomentumParams(**{**P.model_dump(), **bad})
    assert len({(a, b, c) for a in (126, 189, 252) for b in (100, 200) for c in (20, 30)}) == 12


def test_universe_is_every_instrument_ever_a_member():
    s, _ = strat([3, 1, 2])
    assert s.universe(None) == [1, 2, 3]  # type: ignore[arg-type]


def test_selects_top_ranked_trending_stocks_equal_weight():
    s, t = run(range(1, 31), {i: trend(str(0.0005 + i * 0.00002)) for i in range(1, 31)})
    assert len(t) == 20
    assert set(t) == set(range(11, 31))  # steeper trend = higher momentum: top 20 of 30
    assert all(w == D("0.05") for w in t.values())
    assert sum(t.values()) == D(1)


def test_thirty_holdings_weight_is_one_slot_each_and_never_exceeds_full_investment():
    p = MomentumParams(lookback=126, trend_sma=100, holdings=30)
    ids = range(1, 41)
    s, t = run(ids, {i: trend(str(0.0005 + i * 0.00002)) for i in ids}, params=p)
    assert len(t) == 30 and sum(t.values()) <= 1
    assert 1 - sum(t.values()) <= 30 * D("1e-9")  # at most one rounding step per slot


def test_fewer_qualifiers_than_slots_leaves_the_rest_in_cash():
    # 5 up-trending, 25 falling; breadth 5/30 < 50% would force cash, so keep breadth up with
    # many up stocks that fail only the TREND filter is impossible: instead use 12 up of 20.
    ids = list(range(1, 13)) + list(range(101, 109))
    closes = {
        **{i: trend("0.001") for i in range(1, 13)},
        **{i: trend("-0.001") for i in range(101, 109)},
    }
    s, t = run(ids, closes)
    assert set(t) == set(range(1, 13))
    assert all(w == D("0.05") for w in t.values()) and sum(t.values()) == D("0.6")  # 40% cash


def test_stock_below_its_trend_filter_cannot_enter():
    # strong 126-day momentum but the last 10 sessions crash below the 100d SMA
    crash = dict(trend("0.002"))
    p = crash[DAYS[-11]]
    for k, d in enumerate(DAYS[-10:]):
        crash[d] = p * D("0.5") * (1 - D("0.001") * k)
    closes = market() | {999: crash}
    s, t = run(list(closes), closes)
    assert 999 not in t
    row = s.audit[-1]
    assert row["ready"] == len(closes)


def test_breadth_below_50_percent_makes_the_portfolio_cash():
    closes = market(n_up=8, n_down=12)  # only 40% above their 200d SMA
    s, t = run(list(closes), closes)
    assert t == {}
    assert s.audit[-1]["breadth"] == D(40) and s.audit[-1]["selected"] == []


def test_breadth_exactly_50_percent_may_hold():
    closes = market(n_up=10, n_down=10)
    _, t = run(list(closes), closes)
    assert t and set(t) <= set(range(1, 11))


def test_breadth_denominator_keeps_unready_members():
    # 20 of 40 ready members are above their SMA: exactly 50%, so it holds. Two new listings with
    # too little history stay in the denominator: 20/42 = 47.6% < 50%, so the portfolio is cash.
    closes = market(n_up=20, n_down=20)
    _, t = run(list(closes), closes)
    assert t
    short = {i: dict(list(trend("0.001").items())[-100:]) for i in (500, 501)}
    s, t = run(list(closes) + list(short), {**closes, **short})
    row = s.audit[-1]
    assert row["insufficient_history"] == 2 and row["members"] == 42
    assert row["breadth"] == D(20) / D(42) * 100
    assert t == {}


def test_missing_bar_is_visible_and_the_stock_cannot_be_selected():
    closes = market()
    g = dict(closes[3])
    del g[DAYS[-60]]
    closes[3] = g
    s, t = run(list(closes), closes)
    assert 3 not in t
    assert s.audit[-1]["data_gap"] == [3]


def test_too_many_unready_members_is_an_explicit_failure():
    closes = market()
    for i in (1, 2, 3):
        g = dict(closes[i])
        del g[DAYS[-60]]
        closes[i] = g
    with pytest.raises(DataNotReady, match="unready"):
        run(list(closes), closes)  # 3 of 40 = 7.5% > 5%


def test_non_positive_close_is_a_data_gap_not_a_signal():
    closes = market()
    g = dict(closes[2])
    g[DAYS[-30]] = D(0)
    closes[2] = g
    s, t = run(list(closes), closes)
    assert 2 not in t and s.audit[-1]["data_gap"] == [2]


def test_empty_membership_is_an_explicit_failure():
    s = Nifty200TrendMomentum(P, IntervalMembership([Interval(1, date(2030, 1, 1), None)]))
    with pytest.raises(DataNotReady, match="no members"):
        s.on_schedule(ctx_for(Stub({1: trend("0.001")}), LAST))


def test_too_little_market_history_is_an_explicit_failure():
    closes = {i: dict(list(trend("0.001").items())[:100]) for i in range(1, 6)}
    s = Nifty200TrendMomentum(P, members(range(1, 6)))
    with pytest.raises(DataNotReady, match="unready"):
        s.on_schedule(ctx_for(Stub(closes), DAYS[99]))


def test_future_prices_do_not_change_earlier_signals():
    base = market()
    t0 = DAYS[500]
    future = {i: {d: (c if d <= t0 else c * D("7")) for d, c in v.items()} for i, v in base.items()}
    _, a = run(list(base), base, day=t0)
    _, b = run(list(base), future, day=t0)
    assert a == b and a


def test_future_membership_does_not_change_earlier_portfolio():
    base = market()
    t0 = DAYS[500]
    m1 = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in base])
    m2 = IntervalMembership(
        [Interval(i, date(2000, 1, 1), t0 + timedelta(days=1)) for i in list(base)[:10]]
        + [Interval(i, date(2000, 1, 1), None) for i in list(base)[10:]]
        + [Interval(777, t0 + timedelta(days=1), None)]
    )
    a = Nifty200TrendMomentum(P, m1).on_schedule(ctx_for(Stub(base), t0))
    b = Nifty200TrendMomentum(P, m2).on_schedule(ctx_for(Stub(base), t0))
    assert a == b and a


def test_membership_intervals_are_start_inclusive_end_exclusive():
    m = IntervalMembership(
        [Interval(1, date(2020, 1, 1), date(2020, 6, 1)), Interval(2, date(2020, 3, 1), None)]
    )
    assert m.on(date(2019, 12, 31)) == frozenset()
    assert m.on(date(2020, 1, 1)) == {1}
    assert m.on(date(2020, 3, 1)) == {1, 2}
    assert m.on(date(2020, 6, 1)) == {2}
    assert m.ever() == [1, 2]


def test_rebalances_only_on_the_first_decision_of_each_month():
    closes = market()
    s = Nifty200TrendMomentum(P, members(list(closes)))
    stub, calls = Stub(closes), []
    for d in DAYS[500:560]:
        t = s.on_schedule(ctx_for(stub, d))
        if t is not None:
            calls.append(d)
    firsts = [
        min(d for d in DAYS[500:560] if (d.year, d.month) == ym)
        for ym in sorted({(d.year, d.month) for d in DAYS[500:560]})
    ]
    assert calls == firsts


def test_identical_input_gives_identical_output():
    closes = market()
    out = [run(list(closes), closes)[1] for _ in range(3)]
    assert out[0] == out[1] == out[2]
    a, b = (run(list(closes), closes)[0].audit for _ in range(2))
    assert a == b


def test_ties_break_by_instrument_id():
    closes = {i: trend("0.001") for i in range(1, 31)}  # identical paths: every score equal
    _, t = run(list(closes), closes)
    assert set(t) == set(range(1, 21))


def test_baseline_has_no_trend_or_breadth_filter_and_is_otherwise_the_same():
    closes = market(n_up=8, n_down=12)  # breadth 40%: the filtered strategy is in cash
    ids = list(closes)
    base = PlainMomentum(PlainParams(), members(ids))
    t = base.on_schedule(ctx_for(Stub(closes), LAST))
    assert len(t) == 20 and all(w == D("0.05") for w in t.values())
    assert base.requirements() == Nifty200TrendMomentum(P, members(ids)).requirements()
    assert base.id != Nifty200TrendMomentum.id


def test_requirements_cover_the_longest_window_on_split_adjusted_prices():
    r = Nifty200TrendMomentum(P, members([1])).requirements()
    assert r.adjust == "split" and r.lookback_days >= 253 * 7 // 5


def test_params_hash_distinguishes_configurations():
    other = MomentumParams(lookback=252, trend_sma=100, holdings=20)
    assert (
        Nifty200TrendMomentum(P, members([1])).params_hash
        != Nifty200TrendMomentum(other, members([1])).params_hash
    )

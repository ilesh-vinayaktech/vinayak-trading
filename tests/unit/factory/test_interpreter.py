from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.data.reader import AdjBar
from algo.factory import dsl, interpreter
from algo.strategies.nifty200_momentum import DataNotReady


def sessions(n, start=date(2026, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bars(closes, days):
    return [
        AdjBar(
            datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
            D(str(c)),
            D(str(c)),
            D(str(c)),
            D(str(c)),
            D(1000),
            D(1),
        )
        for d, c in zip(days, closes, strict=True)
    ]


def series(start, last, n):
    """n closes: flat at `start` until the 5th-from-last, then a straight line to `last` (so ret_5d = last/start - 1 exactly on the final day)."""
    return [start] * (n - 5) + [start + (last - start) * k / 5 for k in range(1, 6)]


def defn(**over):
    base = {
        "strategy_id": "TEST_001", "version": 1, "description": "test", "universe": "MEMBERS", "timeframe": "DAILY",
        "entry": {"all": [{"feature": "ret_5d", "op": ">", "value": 0.05}]},
        "exit": {"any": [{"feature": "ret_5d", "op": "<", "value": 0}]},
        "ranking": {"feature": "ret_5d", "order": "DESC"},
        "position": {"max_positions": 2, "sizing": "EQUAL_WEIGHT"},
        "risk": {"max_position_percent": 100},
    }  # fmt: skip
    return dsl.StrategyDef.model_validate({**base, **over})


N = 12
DAYS = sessions(N)
DAY = DAYS[-1]


def market(ends):
    """{id: bars} with ret_5d on the last day equal to end / 100 - 1 (every stock starts at 100)."""
    return {i: bars(series(100, e, N), DAYS) for i, e in ends.items()}


def market_on(day, ends):
    allp = sessions(150)
    i = allp.index(day)
    window = allp[i - N + 1 : i + 1]
    return {k: bars(series(100, e, N), window) for k, e in ends.items()}


def decide(d, hist, held=(), members=None):
    return interpreter.decide(d, sorted(members or hist), hist, set(held), DAY)


def test_the_best_ranked_qualifiers_fill_the_free_slots_with_equal_weights():
    targets, audit = decide(defn(), market({1: 110, 2: 108, 3: 106, 4: 101}))
    assert targets == {
        1: D("0.5"),
        2: D("0.5"),
    }  # ret_5d 10% and 8% beat 6%; 1% fails the 5% entry bar
    assert audit["entries"] == [1, 2] and audit["exits"] == {} and audit["ready"] == 4


def test_a_held_stock_stays_until_its_exit_condition_and_new_entries_only_take_what_is_left():
    targets, audit = decide(defn(), market({1: 110, 2: 108, 3: 106, 4: 97}), held={3, 4})
    assert audit["exits"] == {4: "exit_condition"}  # ret_5d -3% < 0
    assert targets == {
        3: D("0.5"),
        1: D("0.5"),
    }  # 3 kept, one free slot to the best of the qualifiers (1, not 2)


def test_more_holdings_than_slots_drops_the_worst_ranked_and_says_so():
    targets, audit = decide(defn(), market({1: 110, 2: 108, 3: 106}), held={1, 2, 3})
    assert set(targets) == {1, 2} and audit["exits"] == {3: "over_limit"}


def test_a_stock_that_left_the_universe_is_sold_whatever_its_signal():
    hist = market({1: 110, 2: 108})
    targets, audit = interpreter.decide(
        defn(), [1], hist, {2}, DAY
    )  # 2 is held but is no longer a member
    assert audit["exits"] == {2: "left_universe"} and targets == {1: D("0.5")}


def test_the_position_cap_binds_and_the_rest_stays_cash():
    targets, _ = decide(defn(risk={"max_position_percent": 30}), market({1: 110, 2: 108}))
    assert targets == {1: D("0.3"), 2: D("0.3")}


def test_inverse_volatility_gives_the_calmer_stock_the_larger_weight():
    n = 40
    days = sessions(n)

    def zigzag(
        a,
    ):  # alternating +a, -a daily moves: its 20-day return volatility is proportional to a
        p, out = 100.0, []
        for k in range(n):
            p *= 1 + (a if k % 2 else -a)
            out.append(p)
        return out

    hist = {1: bars(zigzag(0.02), days), 2: bars(zigzag(0.01), days)}  # 1 is twice as volatile as 2
    d = defn(
        entry={"all": [{"feature": "vol_20d", "op": ">", "value": 0}]},
        exit={"any": [{"feature": "vol_20d", "op": "<", "value": 0}]},
        ranking={"feature": "vol_20d", "order": "ASC"},
        position={"max_positions": 2, "sizing": "INVERSE_VOLATILITY"},
    )
    targets, _ = interpreter.decide(d, [1, 2], hist, set(), days[-1])
    assert targets[2] > targets[1] and sum(targets.values()) <= 1
    assert targets[1] == pytest.approx(D(1) / 3, abs=D("1e-6")) and targets[2] == pytest.approx(
        D(2) / 3, abs=D("1e-6")
    )  # weights in the ratio 1 : 2


def test_a_stock_still_warming_up_is_never_an_entry_and_is_reported_not_dropped_silently():
    hist = {
        1: bars(series(100, 110, N), DAYS),
        2: bars([100, 110, 120], DAYS[-3:]),
    }  # 2 has 3 bars: ret_5d needs 6
    targets, audit = decide(defn(), hist)
    assert targets == {1: D("0.5")} and audit["warming_up"] == [2] and audit["no_bar"] == []


def test_a_held_stock_with_no_bar_today_is_kept_as_it_is_and_too_many_missing_bars_is_a_data_error():
    members = list(range(1, 22))
    hist = {
        i: bars(series(100, 100, N), DAYS) for i in members if i != 21
    }  # 21 has no bars at all today
    hist[1] = bars(series(100, 110, N), DAYS)
    targets, audit = interpreter.decide(defn(), members, hist, {21}, DAY)
    assert 21 in targets and audit["no_bar"] == [
        21
    ]  # 1 of 21 members is 4.8%: tolerated, and the held name is carried
    with pytest.raises(DataNotReady, match="no bar"):
        interpreter.decide(defn(), members, {1: hist[1]}, set(), DAY)  # 20 of 21 missing


def test_ties_in_the_ranking_go_to_the_lower_instrument_id_and_an_ascending_ranking_prefers_the_lowest_value():
    hist = {i: bars(series(100, 110, N), DAYS) for i in (5, 3, 4)}
    targets, _ = decide(defn(position={"max_positions": 1, "sizing": "EQUAL_WEIGHT"}), hist)
    assert set(targets) == {3}
    low = {1: bars(series(100, 106, N), DAYS), 2: bars(series(100, 110, N), DAYS)}
    t2, _ = decide(
        defn(
            ranking={"feature": "ret_5d", "order": "ASC"},
            position={"max_positions": 1, "sizing": "EQUAL_WEIGHT"},
        ),
        low,
    )
    assert set(t2) == {1}


def test_every_comparison_operator_means_what_it_says():
    base = {"feature": "ret_5d", "value": 0.10}
    hist = market({1: 110, 2: 109, 3: 111})
    expected = {">": {3}, ">=": {1, 3}, "<": {2}, "<=": {1, 2}, "==": {1}, "!=": {2, 3}}
    for op, want in expected.items():
        d = defn(
            entry={"all": [{**base, "op": op}]},
            position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"},
        )
        targets, _ = decide(d, hist)
        assert set(targets) == want, op


def test_any_and_all_groups_combine_conditions_as_named():
    hist = market({1: 110, 2: 106})
    wide = {"max_positions": 5, "sizing": "EQUAL_WEIGHT"}
    both = defn(
        entry={
            "all": [
                {"feature": "ret_5d", "op": ">", "value": 0.05},
                {"feature": "ret_5d", "op": ">", "value": 0.08},
            ]
        },
        position=wide,
    )
    either = defn(
        entry={
            "any": [
                {"feature": "ret_5d", "op": ">", "value": 0.05},
                {"feature": "ret_5d", "op": ">", "value": 0.08},
            ]
        },
        position=wide,
    )
    assert set(decide(both, hist)[0]) == {1} and set(decide(either, hist)[0]) == {1, 2}


def test_no_members_on_the_day_is_a_data_error():
    with pytest.raises(DataNotReady, match="no members"):
        interpreter.decide(defn(), [], {}, set(), DAY)


@pytest.mark.parametrize(
    ("rebalance", "days", "decide_on"),
    [
        ("DAILY", [date(2026, 3, 2), date(2026, 3, 3)], [True, True]),
        (
            "WEEKLY",
            [date(2026, 3, 2), date(2026, 3, 4), date(2026, 3, 9)],
            [True, False, True],
        ),  # Monday, Wednesday of the same week, the next Monday
        ("MONTHLY", [date(2026, 3, 31), date(2026, 4, 1), date(2026, 4, 2)], [True, True, False]),
    ],
)
def test_the_rebalance_cadence_decides_once_per_period_and_the_first_call_always_decides(
    rebalance, days, decide_on
):
    gate = interpreter.Cadence(rebalance)
    assert [gate.due(d) for d in days] == decide_on


def test_a_year_boundary_inside_one_iso_week_is_one_period():
    gate = interpreter.Cadence("WEEKLY")
    assert (
        gate.due(date(2025, 12, 31)) is True and gate.due(date(2026, 1, 1)) is False
    )  # Wednesday and Thursday of ISO week 1


def test_a_stock_without_a_usable_volatility_gets_the_equal_share_under_inverse_volatility_sizing():
    n = 40
    days = sessions(n)
    flat = bars(
        [100] * n, days
    )  # zero volatility: 1 / vol is undefined, so the name is sized at the equal share, not dropped
    d = defn(
        entry={"all": [{"feature": "vol_20d", "op": ">=", "value": 0}]},
        exit={"any": [{"feature": "vol_20d", "op": "<", "value": 0}]},
        ranking={"feature": "vol_20d", "order": "ASC"},
        position={"max_positions": 4, "sizing": "INVERSE_VOLATILITY"},
    )
    targets, _ = interpreter.decide(d, [1], {1: flat}, set(), days[-1])
    assert targets == {1: D("0.25")}


# ---- found by mutation testing ---------------------------------------------------------------------------------------
def test_the_audit_row_has_exactly_these_keys_and_values():
    _, audit = decide(defn(), market({1: 110, 2: 108, 3: 106, 4: 101}), held={9})
    assert audit == {
        "day": str(DAY), "members": 4, "ready": 4, "no_bar": [], "warming_up": [],
        "held": [9], "exits": {9: "left_universe"}, "entries": [1, 2],
    }  # fmt: skip


def test_entries_follow_the_ranking_even_when_the_best_stock_has_the_higher_id():
    targets, audit = decide(
        defn(position={"max_positions": 1, "sizing": "EQUAL_WEIGHT"}), market({1: 106, 2: 110})
    )
    assert set(targets) == {2} and audit["entries"] == [2]


def test_when_every_slot_is_held_nothing_new_enters():
    targets, audit = decide(defn(), market({1: 106, 2: 106, 3: 120}), held={1, 2})
    assert set(targets) == {1, 2} and audit["entries"] == []


def test_exactly_five_percent_of_members_without_a_bar_is_tolerated():
    members = list(range(1, 21))
    hist = {i: bars(series(100, 100, N), DAYS) for i in members if i != 20}  # 1 of 20 = exactly 5%
    targets, audit = interpreter.decide(defn(), members, hist, set(), DAY)
    assert audit["no_bar"] == [20] and targets == {}


def test_over_the_limit_the_stocks_that_cannot_be_traded_are_kept_and_the_worst_ranked_tradable_one_is_dropped():
    members = list(range(1, 26))
    hist = {
        i: bars(series(100, 100, N), DAYS) for i in members if i != 25
    }  # 25 has no bar: it cannot be sold
    hist[1], hist[2] = bars(series(100, 110, N), DAYS), bars(series(100, 108, N), DAYS)
    targets, audit = interpreter.decide(
        defn(), members, hist, {1, 2, 25}, DAY
    )  # three held, two slots
    assert set(targets) == {1, 25} and audit["exits"] == {2: "over_limit"}


def test_weights_are_rounded_down_to_a_billionth_so_the_total_can_never_exceed_the_whole():
    targets, _ = decide(
        defn(position={"max_positions": 7, "sizing": "EQUAL_WEIGHT"}),
        market({i: 110 + i for i in range(1, 8)}),
    )
    assert set(targets.values()) == {D("0.142857142")} and sum(targets.values()) < 1


def test_a_traded_value_condition_reads_the_bars_close_and_volume():
    def vol_bars(volume):
        return [
            AdjBar(
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                D(100),
                D(100),
                D(100),
                D(100),
                D(volume),
                D(1),
            )
            for d in sessions(30)
        ]

    days = sessions(30)
    wide = {"max_positions": 5, "sizing": "EQUAL_WEIGHT"}
    over = defn(
        entry={"all": [{"feature": "traded_value_20d", "op": ">", "value": 99999}]}, position=wide
    )
    at = defn(
        entry={"all": [{"feature": "traded_value_20d", "op": ">", "value": 100000}]}, position=wide
    )
    hist = {1: vol_bars(1000)}  # 100 x 1000 = 100,000 a day
    assert set(interpreter.decide(over, [1], hist, set(), days[-1])[0]) == {1}
    assert interpreter.decide(at, [1], hist, set(), days[-1])[0] == {}


# ---- the Strategy itself, with a stand-in for Context ------------------------------------------------------------------
class FakeData:
    def __init__(self, hist):
        self.hist, self.calls = hist, []

    def history(self, ids, lookback_days):
        self.calls.append((list(ids), lookback_days))
        return {i: self.hist[i] for i in ids if i in self.hist}


class FakePortfolio:
    def __init__(self, positions):
        self.positions = positions


class FakeCtx:
    def __init__(self, day, hist, positions=(), mode="research"):
        self._now, self.mode = datetime(day.year, day.month, day.day, 10, tzinfo=UTC), mode
        self.data, self.portfolio = FakeData(hist), FakePortfolio({i: D(1) for i in positions})

    def now(self):
        return self._now


def strategy(rebalance="DAILY", unusable=None, members=(1, 2)):
    from algo.data.universe import Interval
    from algo.strategies.nifty200_momentum import IntervalMembership

    m = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in members], unusable)
    return interpreter.DslStrategy(defn(rebalance=rebalance), m)


def test_the_strategy_carries_its_identity_asks_for_the_history_the_definition_needs_and_decides():
    s = strategy()
    assert (s.id, s.version, s.params_hash) == ("TEST_001", "1", s.defn.sha256[:16])
    assert s.universe(None) == [1, 2]  # type: ignore[arg-type]
    req = s.requirements()
    assert (req.lookback_days, req.adjust) == (
        39,
        "split",
    )  # ret_5d needs 6 bars: ceil(6 x 7 / 5) + 30 calendar days
    ctx = FakeCtx(DAY, market({1: 110, 2: 108}), positions=(7,))
    assert s.on_schedule(ctx) == {1: D("0.5"), 2: D("0.5")}
    assert ctx.data.calls == [
        ([1, 2, 7], req.lookback_days)
    ]  # members, then a held stock that is no longer one
    assert s.audit[0]["exits"] == {7: "left_universe"}


def test_between_rebalance_days_the_strategy_makes_no_decision_and_asks_for_no_data():
    s = strategy(rebalance="WEEKLY")
    monday, tuesday = date(2026, 3, 2), date(2026, 3, 3)
    first = FakeCtx(monday, market_on(monday, {1: 110, 2: 108}))
    assert s.on_schedule(first) is not None
    second = FakeCtx(tuesday, market_on(tuesday, {1: 110, 2: 108}))
    assert s.on_schedule(second) is None and second.data.calls == []


def test_in_strict_mode_an_unusable_membership_day_is_skipped_and_the_period_is_not_used_up():
    s = strategy(rebalance="WEEKLY", unusable={DAY: "not verified"})
    ctx = FakeCtx(DAY, market({1: 110, 2: 108}), mode="strict")
    assert s.on_schedule(ctx) is None and ctx.data.calls == []
    assert s.audit == [
        {
            "day": str(DAY),
            "skipped": "strict: membership evidence unusable",
            "reasons": "not verified",
        }
    ]
    assert (
        s.on_schedule(FakeCtx(DAY, market({1: 110, 2: 108}))) is not None
    )  # a research-mode call the same week still decides


def test_the_strategy_has_a_real_empty_parameter_object_because_the_engine_records_it():
    s = strategy()
    assert s.params == interpreter.NoParams() and s.params.model_dump_json() == "{}"


# ---- cross-sectional percentile conditions: no data-derived threshold, the day's own ranking decides -------------------------------------------------------
TEN = {i: 100 + i for i in range(1, 11)}  # ret_5d 1% .. 10%: stock 10 is the strongest


def pct(op, value, group="entry", **kw):
    cond = {"feature": "ret_5d", "op": op, "value": value}
    return defn(**{group: {"any" if group == "exit" else "all": [cond]}}, **kw)


def test_top_percent_takes_the_strongest_share_of_the_stocks_that_have_data_that_day():
    d = pct("TOP_PERCENT", 20, position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"})
    targets, audit = decide(d, market(TEN))
    assert audit["entries"] == [10, 9] and sorted(targets) == [
        9,
        10,
    ]  # 20% of 10 is two stocks, best first


def test_bottom_percent_takes_the_weakest_share_and_the_share_is_rounded_up_never_down():
    d = pct("BOTTOM_PERCENT", 25, position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"})
    _, audit = decide(d, market(TEN))
    assert sorted(audit["entries"]) == [
        1,
        2,
        3,
    ]  # 25% of 10 is 2.5: three stocks, and at least one is always taken
    one = pct("TOP_PERCENT", 1, position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"})
    assert decide(one, market(TEN))[1]["entries"] == [10]
    everyone = pct("TOP_PERCENT", 100, position={"max_positions": 10, "sizing": "EQUAL_WEIGHT"})
    assert sorted(decide(everyone, market(TEN))[1]["entries"]) == list(range(1, 11))


def test_ties_in_a_percentile_go_to_the_lower_instrument_id_and_stocks_without_data_are_not_counted():
    d = pct("TOP_PERCENT", 25, position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"})
    tied = {1: 105, 2: 105, 3: 105, 4: 105}
    assert decide(d, market(tied))[1]["entries"] == [
        1
    ]  # 25% of 4 is one stock; equal values: the lowest id
    hist = market(tied)
    hist[5] = bars([100] * 3, DAYS[-3:])  # three bars only: still warming up, so not in the ranking
    _, audit = decide(d, hist)
    assert audit["warming_up"] == [5] and audit["entries"] == [1] and audit["ready"] == 4


def test_a_percentile_exit_sells_a_holding_that_has_fallen_into_the_bottom_half_and_keeps_the_rest():
    d = pct(
        "BOTTOM_PERCENT",
        50,
        group="exit",
        entry={"all": [{"feature": "ret_5d", "op": ">", "value": 0.5}]},
        position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"},
    )
    targets, audit = decide(d, market(TEN), held={5, 6})
    assert (
        audit["exits"] == {5: "exit_condition"} and 6 in targets and 5 not in targets
    )  # 5 is the 5th weakest of 10; 6 is in the top half


def test_percentile_and_threshold_conditions_combine_in_one_group():
    d = defn(
        entry={
            "all": [
                {"feature": "ret_5d", "op": "TOP_PERCENT", "value": 30},
                {"feature": "ret_5d", "op": ">", "value": 0.085},
            ]
        },
        position={"max_positions": 5, "sizing": "EQUAL_WEIGHT"},
    )
    assert decide(d, market(TEN))[1]["entries"] == [
        10,
        9,
    ]  # the top three are 10, 9 and 8; 8% does not clear 8.5%

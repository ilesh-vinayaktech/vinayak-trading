# ruff: noqa: E501
"""One stock's buy/sell decisions under a generated definition, read from stored feature values: the same cross-sectional rule as the interpreter, applied to one name."""

from datetime import date, timedelta
from decimal import Decimal as D

from algo.factory import generate, signals

DEFN = generate.definition_for(
    generate.Hypothesis(1, 1, "ret_20d", "1", 1, "POSITIVE", 0.05, 0.001)
)  # daily, buy the top 20%, sell in the bottom 50%
D0 = date(2024, 3, 4)  # a Monday


def day(i):
    return D0 + timedelta(days=i)


def book(rows):
    """rows: {day index: {instrument: value}} for the one feature."""
    return {"ret_20d": {day(i): {k: D(str(v)) for k, v in r.items()} for i, r in rows.items()}}


def run(rows, iid=1, n=None):
    days = [day(i) for i in range(n or len(rows))]
    return signals.decide(DEFN, book(rows), iid, days)


def test_a_stock_in_the_top_fifth_is_bought_and_sold_when_it_falls_into_the_bottom_half():
    ten = lambda top: {i: (top if i == 1 else i / 100) for i in range(1, 11)}  # noqa: E731 - stock 1 is `top`, the others 0.02 .. 0.10
    got = run({0: ten(0.5), 1: ten(0.5), 2: ten(0.0), 3: ten(0.0)})
    assert [(g.action, g.holding_after) for g in got] == [
        ("BUY", True),
        (None, True),
        ("SELL", False),
        (None, False),
    ]


def test_a_stock_that_never_makes_the_top_fifth_is_never_bought():
    rows = {i: {k: k / 10 for k in range(1, 11)} for i in range(3)}  # stock 1 is always last
    assert [g.action for g in run(rows)] == [None, None, None]


def test_a_day_without_a_value_for_the_stock_is_not_ready_and_changes_nothing():
    rows = {0: {k: k for k in range(2, 12)}, 1: {k: k for k in range(1, 11)}}
    got = run(rows)
    assert [(g.ready, g.action) for g in got] == [(False, None), (True, None)]


def test_a_monthly_definition_only_decides_on_the_first_session_of_a_month():
    monthly = generate.definition_for(
        generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
    )
    rows = {i: {k: (9 if k == 1 else k / 100) for k in range(1, 11)} for i in range(3)}
    got = signals.decide(monthly, book(rows), 1, [day(i) for i in range(3)])
    assert [g.action for g in got] == [
        "BUY",
        None,
        None,
    ]  # the first day of the period decides; the rest keep it


def test_the_notes_say_what_this_is_not():
    assert any("not a backtest" in n for n in signals.NOTES) and any(
        "kept nowhere" in n for n in signals.NOTES
    )


def _bars(closes, first=date(2024, 12, 2)):
    from datetime import UTC, datetime
    from decimal import Decimal as Dc

    from algo.data.reader import AdjBar

    out, d = [], first
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(
            AdjBar(
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                Dc(c),
                Dc(c),
                Dc(c),
                Dc(c),
                Dc(1000),
                datetime(d.year, d.month, d.day, 12, tzinfo=UTC),
            )
        )
        d += timedelta(days=1)
    return out


def test_values_after_the_stored_days_are_computed_from_bars_in_memory_for_the_universe_only():
    series = {
        1: [100 + 2 * k for k in range(40)],
        2: [100 + k for k in range(40)],
        3: [100 - k for k in range(40)],
    }
    calls = []

    def bars_of(i, lo, hi):
        calls.append(i)
        return _bars(series[i])

    after = _bars(series[1])[25].ts.date()
    got = signals.tail_values(DEFN, {1, 2}, after, _bars(series[1])[-1].ts.date(), bars_of)
    assert sorted(set(calls)) == [1, 2]  # stock 3 is not in the universe: never read
    days = sorted(got["ret_20d"])
    assert days and days[0] > after  # only days after the stored ones
    assert all(set(v) == {1, 2} for v in got["ret_20d"].values())
    assert all(
        got["ret_20d"][d][1] > got["ret_20d"][d][2] for d in days
    )  # the faster riser has the higher 20-day return


def test_continuing_from_a_stored_state_gives_exactly_what_a_full_run_gives():
    for defn in (
        DEFN,
        generate.definition_for(
            generate.Hypothesis(1, 1, "ret_20d", "1", 20, "POSITIVE", 0.05, 0.001)
        ),
    ):
        rows = {
            i: {k: (9 if k == 1 and i < 3 else k / 100) for k in range(1, 11)} for i in range(6)
        }
        vals = book(rows)
        days = [day(i) for i in range(6)]
        full = signals.decide(defn, vals, 1, days)
        head = signals.decide(defn, vals, 1, days[:3])
        tail = signals.decide(defn, vals, 1, days[3:], held=head[-1].holding_after, after=days[2])
        assert head + tail == full


def test_every_decision_says_which_conditions_passed_or_failed_with_the_numbers():
    ten = lambda top: {i: (top if i == 1 else i / 100) for i in range(1, 11)}  # noqa: E731
    got = run({0: ten(0.5), 1: ten(0.0)})
    buy, sell = got[0].reason, got[1].reason
    assert buy.splitlines()[0] == "Buy: the entry rule holds (all of these must pass)"
    assert "ret_20d is in the highest 20%: rank 1 of 10, needs 2 or better (value 0.5): PASS" in buy
    assert sell.splitlines()[0] == "Sell: the exit rule holds (any of these is enough)"
    assert "ret_20d is in the lowest 50%: rank 1 of 10, needs 5 or better (value 0): PASS" in sell


def test_a_threshold_condition_shows_its_comparison_and_a_failed_one_is_listed_too():
    from algo.factory.dsl import StrategyDef

    raw = DEFN.canonical()
    raw["entry"] = {
        "all": [
            {"feature": "ret_20d", "op": ">", "value": 0},
            {"feature": "ret_20d", "op": "TOP_PERCENT", "value": 20},
        ]
    }
    both = StrategyDef.model_validate(raw)
    rows = {0: {k: (0.5 if k == 1 else k / 100) for k in range(1, 11)}}
    got = signals.decide(both, book(rows), 1, [day(0)])
    assert got[0].action == "BUY"
    assert "ret_20d > 0: value 0.5: PASS" in got[0].reason and got[0].reason.count("PASS") == 2
    raw["entry"] = {
        "any": [
            {"feature": "ret_20d", "op": "<", "value": 0},
            {"feature": "ret_20d", "op": "TOP_PERCENT", "value": 20},
        ]
    }
    either = StrategyDef.model_validate(raw)
    got = signals.decide(either, book(rows), 1, [day(0)])
    assert (
        "ret_20d < 0: value 0.5: FAIL" in got[0].reason and "PASS" in got[0].reason
    )  # one failed, one passed: enough for 'any'

# ruff: noqa: E501
"""A screener strategy that ranks and filters on the swing score, read from a ScoreBook of scores as known on each day. ENGINEERING_TEST_ONLY: synthetic data."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from algo.strategies.scorebook import ScoreBook
from algo.strategies.screener import ScreenerParams, ScreenerStrategy, ScreenSpec
from tests.unit.strategies.test_nifty200_momentum import LAST, Stub
from tests.unit.strategies.test_trend_pullback import ctx_with, members, uptrend

TOP = {"field": "score", "op": "gt", "value": 60}


def spec(*conds, sort="score", descending=True):
    return ScreenSpec.model_validate(
        {"conditions": list(conds), "sort": sort, "descending": descending}
    )


def book(scores: dict[int, float], on=LAST - timedelta(days=3)):
    return ScoreBook({i: [(on, {"score": v})] for i, v in scores.items()})


def run(closes, scores, screen, slots=5):
    s = ScreenerStrategy(
        ScreenerParams(max_positions=slots), members(list(closes)), screen, None, scores
    )
    return s.on_schedule(ctx_with(Stub(closes), LAST))


def test_the_best_scores_above_the_bar_are_bought_and_unscored_or_low_stocks_are_not():
    closes = {i: uptrend() for i in range(1, 8)}
    got = run(
        closes, book({1: 90, 2: 80, 3: 70, 4: 65, 5: 55, 6: 40}), spec(TOP), slots=5
    )  # 7 has no score at all
    assert set(got) == {
        1,
        2,
        3,
        4,
    }  # 5 and 6 are under the bar, 7 has no figure: a screen never matches on "unknown"


def test_slots_go_to_the_highest_scores_first():
    closes = {i: uptrend() for i in range(1, 8)}
    got = run(closes, book({i: 60 + i for i in range(1, 8)}), spec(TOP), slots=5)
    assert set(got) == {3, 4, 5, 6, 7}


def test_a_score_dated_after_the_decision_day_is_not_used():
    closes = {i: uptrend() for i in range(1, 4)}
    future = book({1: 99, 2: 99, 3: 99}, on=LAST + timedelta(days=1))
    assert (
        run(closes, future, spec(TOP)) is None
    )  # nothing matches yet: no order, rather than trading on a score from the future


def test_a_stale_score_is_not_used():
    closes = {i: uptrend() for i in range(1, 4)}
    assert run(closes, book({1: 99}, on=LAST - timedelta(days=30)), spec(TOP)) is None


def test_a_screen_that_reads_the_score_cannot_be_built_without_a_score_book():
    with pytest.raises(ValueError, match="ScoreBook"):
        ScreenerStrategy(ScreenerParams(), members([1]), spec(TOP), None, None)


def test_a_screen_may_use_the_numeric_score_fields_but_not_the_text_ones_or_smart_money_as_of_today():
    assert spec(TOP).needs_scores() and spec(TOP).problem() is None
    assert (
        spec(
            {"field": "score_participation", "op": "gt", "value": 50}, sort="score_trend"
        ).problem()
        is None
    )
    assert not spec({"field": "rsi_14", "op": "lt", "value": 30}, sort="rsi_14").needs_scores()
    assert "setup" in (
        spec({"field": "setup", "op": "eq", "value": "Accumulation"}, sort="score").problem() or ""
    )
    assert "deal_net_30d" in (
        spec({"field": "deal_net_30d", "op": "gt", "value": 1}, sort="score").problem() or ""
    )


def test_a_score_screen_mixes_with_price_fields():
    closes = {1: uptrend("0.002"), 2: uptrend("-0.001")}  # 2 has the better score but is falling
    got = run(closes, book({1: 70, 2: 90}), spec(TOP, {"field": "chg_3m", "op": "gt", "value": 0}))
    assert got == {1: D("0.2")}


def test_a_market_regime_condition_switches_the_whole_screen_off_in_fear_and_back_on():
    closes = {i: uptrend() for i in range(1, 5)}
    gate = {"field": "mkt_fear_greed", "op": "gt", "value": 30}
    s = spec(TOP, gate)
    assert s.problem() is None and s.needs_scores()

    def go(fear):
        market = [(LAST - timedelta(days=1), {"mkt_fear_greed": fear})]
        scores = ScoreBook(
            {i: [(LAST - timedelta(days=3), {"score": 80.0})] for i in closes}, market
        )
        return run(closes, scores, s)

    assert go(55.0) is not None and set(go(55.0)) == {
        1,
        2,
        3,
        4,
    }  # calm market: the scored stocks are bought
    assert go(20.0) is None  # extreme fear: nothing matches, so nothing is bought

"""A screener strategy that reads filed ratios, alone or with price fields. ENGINEERING_TEST_ONLY: synthetic data."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D

import pytest

from algo.data.ratios import Quarter
from algo.strategies.fundamentals import FundamentalsBook
from algo.strategies.screener import ScreenerParams, ScreenerStrategy, ScreenSpec
from tests.unit.strategies.test_fundamentals import EPS, NOW, quarters
from tests.unit.strategies.test_nifty200_momentum import LAST, Stub
from tests.unit.strategies.test_trend_pullback import ctx_with, members, uptrend

PE = {"field": "pe", "op": "lt", "value": 1000000}


def spec(*conds, sort="pe", descending=False):
    return ScreenSpec.model_validate(
        {"conditions": list(conds), "sort": sort, "descending": descending}
    )


def run(closes, book, screen, slots=20):
    s = ScreenerStrategy(ScreenerParams(max_positions=slots), members(list(closes)), screen, book)
    return s.on_schedule(ctx_with(Stub(closes), LAST))


def book(eps: dict[int, float], late=()):
    """Same price for every stock, so P/E falls as earnings rise; `late` stocks file after the day."""
    return FundamentalsBook(
        {(i, "CONSOLIDATED"): quarters(e, late=100 if i in late else 0) for i, e in eps.items()},
        {},
        {},
    )


def test_a_fundamental_only_screen_ranks_by_the_ratio_and_skips_what_has_no_figure():
    closes = {i: uptrend() for i in range(1, 11)}
    eps = {
        1: 1,
        2: 2,
        3: 3,
        4: 4,
        5: 5,
        6: 6,
        7: 7,
        8: -1,
        10: 9,
    }  # 8 loses money (no P/E), 9 has no filings, 10 files too late
    t = run(closes, book(eps, late=[10]), spec(PE), slots=20)
    assert set(t) == {1, 2, 3, 4, 5, 6, 7}
    top = run(closes, book(eps, late=[10]), spec(PE), slots=5)
    assert set(top) == {3, 4, 5, 6, 7}  # lowest P/E = highest earnings first


def test_a_combined_screen_needs_both_the_price_condition_and_the_ratio():
    closes = {1: uptrend("0.002"), 2: uptrend("-0.001")}  # 2 is cheap but falling
    t = run(
        closes,
        book({1: 5, 2: 50}),
        spec({"field": "chg_3m", "op": "gt", "value": 0}, PE, sort="pe"),
    )
    assert t == {1: D("0.05")}


def test_a_screen_that_reads_filings_cannot_be_built_without_them():
    with pytest.raises(ValueError, match="FundamentalsBook"):
        ScreenerStrategy(ScreenerParams(), members([1]), spec(PE), None)


def test_a_screen_may_use_price_fields_and_filed_ratios_but_not_a_market_cap_class():
    assert spec(PE).needs_fundamentals()
    assert not spec(
        {"field": "rsi_14", "op": "lt", "value": 30}, sort="rsi_14"
    ).needs_fundamentals()
    assert spec(PE).problem() is None
    seg = spec({"field": "segment", "op": "eq", "value": "large"}, sort="pe")
    assert "market-cap class" in (seg.problem() or "")
    assert "nope" in (spec({"field": "nope", "op": "gt", "value": 1}).problem() or "")


def future_quarter(eps, filed_in_days):
    """A quarter that is filed `filed_in_days` after the decision day, with figures that would change any decision."""
    end = LAST + timedelta(days=filed_in_days - 45)
    figures = {
        EPS: D(eps),
        "PaidUpValueOfEquityShareCapital": D(1000),
        "FaceValueOfEquityShareCapital": D(10),
    }
    return Quarter(end, datetime.combine(end + timedelta(days=45), time(10), UTC), False, figures)


def test_filings_made_after_the_decision_day_cannot_change_that_days_decision():
    closes = {i: uptrend() for i in range(1, 4)}
    spec_pe = spec(PE)
    known_only = FundamentalsBook(
        {(1, "CONSOLIDATED"): quarters(2), (2, "CONSOLIDATED"): quarters(5)}, {}, {}
    )
    ahead = future_quarter(
        1000, filed_in_days=30
    )  # 500x the earnings of the others: it would reorder everything
    with_future = FundamentalsBook(
        {
            (1, "CONSOLIDATED"): [ahead, *quarters(2)],
            (2, "CONSOLIDATED"): quarters(5),
            (3, "CONSOLIDATED"): [ahead],  # a stock whose only filing is still to come
        },
        {},
        {},
    )
    assert run(closes, with_future, spec_pe) == run(closes, known_only, spec_pe)
    assert set(run(closes, with_future, spec_pe)) == {1, 2}
    # the same future filing does count once its day has come, so the test above can fail
    later = NOW + timedelta(days=60)
    assert with_future.ratios(1, later, D(200), later.date()) != known_only.ratios(
        1, later, D(200), later.date()
    )

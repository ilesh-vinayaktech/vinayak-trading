"""Filed ratios as known on a past day. ENGINEERING_TEST_ONLY: synthetic filings, nothing here is a strategy result."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal as D

from algo.data.ratios import Quarter
from algo.strategies.fundamentals import FundamentalsBook
from tests.unit.strategies.test_nifty200_momentum import LAST

EPS = "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"
NOW = datetime.combine(LAST, time(12, 0), UTC)


def quarters(eps, late=0):
    """Four consecutive quarters, newest first; each is filed 45 days (+ `late`) after it ends. Newest ended 60 days before LAST."""
    out = []
    for i in range(4):
        end = LAST - timedelta(days=60 + 91 * i)
        figures = {
            EPS: D(eps),
            "PaidUpValueOfEquityShareCapital": D(1000),
            "FaceValueOfEquityShareCapital": D(10),
        }
        out.append(
            Quarter(
                end,
                datetime.combine(end + timedelta(days=45 + late), time(10), UTC),
                False,
                figures,
            )
        )
    return out


def book(qs=None, basis="CONSOLIDATED", splits=(), dividends=()):
    return FundamentalsBook(
        {(1, basis): qs or quarters(10)}, {1: list(splits)}, {1: list(dividends)}
    )


def test_a_ratio_is_worked_out_from_the_filings_and_the_price_of_that_day():
    assert book().ratios(1, NOW, D(200), LAST)["pe"] == D(5)  # 200 / (4 quarters x 10)


def test_a_filing_made_after_the_day_is_invisible_until_the_day_it_is_filed():
    b = book(quarters(10, late=100))
    assert (
        b.ratios(1, NOW, D(200), LAST)["pe"] is None
    )  # the newest quarter is filed 85 days from now: no four quarters known yet
    later = NOW + timedelta(days=200)
    assert b.ratios(1, later, D(200), later.date())["pe"] == D(5)


def test_a_stock_with_no_filings_has_no_ratios_and_consolidated_wins_over_standalone():
    assert book().ratios(2, NOW, D(200), LAST) == {}
    both = FundamentalsBook(
        {(1, "CONSOLIDATED"): quarters(10), (1, "STANDALONE"): quarters(20)}, {}, {}
    )
    assert both.ratios(1, NOW, D(200), LAST)["pe"] == D(5)
    assert book(basis="STANDALONE").ratios(1, NOW, D(200), LAST)["pe"] == D(5)


def test_a_split_after_the_latest_results_blanks_the_per_share_ratios_one_before_does_not():
    assert book(splits=[LAST - timedelta(days=5)]).ratios(1, NOW, D(200), LAST)["pe"] is None
    assert book(splits=[LAST - timedelta(days=30)]).ratios(1, NOW, D(200), LAST)["pe"] == D(5)


def test_dividend_yield_counts_only_the_last_twelve_months_up_to_the_day():
    divs = [
        (LAST - timedelta(days=400), D(9)),
        (LAST - timedelta(days=100), D(2)),
        (LAST - timedelta(days=30), D(3)),
        (LAST + timedelta(days=3), D(7)),
    ]
    assert book(dividends=divs).ratios(1, NOW, D(200), LAST)["dividend_yield"] == D(
        "2.5"
    )  # (2 + 3) / 200
    assert book().ratios(1, NOW, D(200), LAST)["dividend_yield"] is None

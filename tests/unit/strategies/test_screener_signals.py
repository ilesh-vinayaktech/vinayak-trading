"""One stock's buy/sell decisions under a screener strategy, on a synthetic series. ENGINEERING_TEST_ONLY: nothing here is a
strategy experiment and none of it may enter the validation registry."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D

from algo.data.reader import AdjBar
from algo.strategies.screener import ScreenSpec
from algo.strategies.screener_signals import replay

ALWAYS = ScreenSpec.model_validate(  # holds on every day
    {"conditions": [{"field": "price", "op": "gt", "value": 0}], "sort": "price"}
)
CHEAP = ScreenSpec.model_validate(  # holds while the close is below 30
    {"conditions": [{"field": "price", "op": "lt", "value": 30}], "sort": "price"}
)
EXPENSIVE = ScreenSpec.model_validate(  # holds from the day the close reaches 30
    {"conditions": [{"field": "price", "op": "gte", "value": 30}], "sort": "price"}
)


def sessions(n, start=date(2025, 1, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions(100)
BARS = [  # the close rises 10, 11, 12 ...
    AdjBar(datetime.combine(d, time(3, 45), UTC), D(10 + i), D(10 + i), D(10 + i), D(10 + i), D(1000), D(1), 1)
    for i, d in enumerate(DAYS)
]  # fmt: skip
FIRST_30 = DAYS[20]  # close 30


def marks(rows):
    return [(r.day, r.action) for r in rows if r.action]


def test_a_stock_is_bought_the_day_it_starts_matching_and_sold_the_day_it_stops():
    rows = replay(BARS, DAYS[0], DAYS[-1], CHEAP)
    assert marks(rows) == [(DAYS[0], "BUY"), (FIRST_30, "SELL")]
    sell = next(r for r in rows if r.action == "SELL")
    assert sell.holding_after is False and sell.reason == "no longer matches the screen"
    assert not any(r.holding_after for r in rows if r.day >= FIRST_30)  # and it is not bought back


def test_a_stock_that_begins_matching_later_is_bought_on_that_day():
    rows = replay(BARS, DAYS[0], DAYS[-1], EXPENSIVE)
    assert marks(rows) == [(FIRST_30, "BUY")]
    buy = rows[20]
    assert buy.reason == "matches the screen" and buy.holding_after is True
    assert buy.fill_day == DAYS[21] and buy.fill_price == D(
        10 + 21
    )  # filled at the next session's open


def test_a_stock_already_matching_when_the_range_starts_is_not_bought_again():
    rows = replay(BARS, DAYS[5], DAYS[-1], CHEAP)
    assert marks(rows) == [(FIRST_30, "SELL")]  # it was already in the buy zone before the range
    assert rows[0].day == DAYS[5] and rows[0].holding_after is True


def test_a_stock_that_matched_only_before_the_range_shows_as_not_held():
    rows = replay(BARS, DAYS[40], DAYS[-1], CHEAP)
    assert marks(rows) == [] and not any(r.holding_after for r in rows)


def test_a_stock_matching_all_along_is_bought_once_and_never_sold():
    assert marks(replay(BARS, DAYS[0], DAYS[-1], ALWAYS)) == [(DAYS[0], "BUY")]


def test_the_last_bar_has_no_fill_and_the_range_is_cut_to_its_end():
    rows = replay(BARS, DAYS[0], DAYS[-1], EXPENSIVE)
    assert rows[-1].day == DAYS[-1]
    cut = replay(BARS, DAYS[0], DAYS[10], ALWAYS)
    assert cut[-1].day == DAYS[10] and marks(cut) == [(DAYS[0], "BUY")]
    last = replay(BARS[:1], DAYS[0], DAYS[0], ALWAYS)
    assert last[0].action == "BUY" and last[0].fill_day is None and last[0].fill_price is None


def test_a_decision_reads_nothing_after_its_own_day():
    full = replay(BARS, DAYS[0], DAYS[-1], CHEAP)
    for k in (5, 20, 60):
        cut = replay(BARS[: k + 1], DAYS[0], DAYS[k], CHEAP)
        assert [(r.day, r.action, r.holding_after) for r in cut] == [
            (r.day, r.action, r.holding_after) for r in full[: k + 1]
        ]


def test_the_same_inputs_give_the_same_decisions():
    a = replay(BARS, DAYS[0], DAYS[-1], CHEAP)
    assert a == replay(BARS, DAYS[0], DAYS[-1], CHEAP)


def test_a_filed_ratio_screen_reads_the_filings_known_on_each_day():
    from datetime import UTC, datetime, time, timedelta
    from decimal import Decimal as D

    from algo.data.ratios import Quarter
    from algo.strategies.fundamentals import FundamentalsBook

    eps = "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"
    figures = {
        eps: D(10),
        "PaidUpValueOfEquityShareCapital": D(1000),
        "FaceValueOfEquityShareCapital": D(10),
    }
    filed = DAYS[40]  # every quarter is filed on this day: before it nothing is known
    qs = [
        Quarter(
            filed - timedelta(days=45 + 91 * i),
            datetime.combine(filed, time(10), UTC),
            False,
            figures,
        )
        for i in range(4)
    ]
    spec = ScreenSpec.model_validate(
        {"conditions": [{"field": "pe", "op": "lt", "value": 1000000}], "sort": "pe"}
    )
    rows = replay(
        BARS, DAYS[0], DAYS[-1], spec, FundamentalsBook({(1, "CONSOLIDATED"): qs}, {}, {}), 1
    )
    buys = [r.day for r in rows if r.action == "BUY"]
    assert buys == [
        filed
    ]  # the screen starts matching the day the results become known, not earlier

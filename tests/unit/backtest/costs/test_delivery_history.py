"""Equity delivery charges as they were on each trade date, 2016 to now (config/cost_schedules/history_delivery_*.json).

The rates and the dates they changed come from stored documents (see scripts/build_cost_schedules.py, which refuses to build
a rate whose quote is not literally in its document); these tests pin the behaviour a backtest relies on: no gaps, the right
rate on each side of every change, GST only from its start, and exact charge totals worked out by hand."""

from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.calculator import compute_charges
from algo.backtest.costs.schedule import NoScheduleForDate, ScheduleBook, load_schedules

CFG = Path(__file__).parents[4] / "config/cost_schedules"
ALL = ("extracted_unverified", "assumed_backfill")
BOOK = ScheduleBook(load_schedules(CFG), allowed_statuses=ALL)


def comp(day, type_):
    return next((c for c in BOOK.for_date(day).components if c.type == type_), None)


def test_delivery_is_covered_every_day_from_2016_without_gaps_or_overlaps():
    cover = BOOK.coverage("DELIVERY")
    assert cover[0][0] == date(2016, 1, 1) and cover[-1][1] is None
    for (_, until), (nxt, _) in zip(cover, cover[1:], strict=False):
        assert (
            until is not None and until + timedelta(days=1) == nxt
        )  # the next one starts the very next day
    with pytest.raises(NoScheduleForDate):
        BOOK.for_date(date(2015, 12, 31))  # nothing is guessed before the history starts


@pytest.mark.parametrize(
    ("day", "rate"),
    [
        (date(2016, 1, 1), "0.00345"), (date(2023, 3, 31), "0.00345"),
        (date(2023, 4, 1), "0.00325"), (date(2024, 3, 31), "0.00325"),
        (date(2024, 4, 1), "0.00322"), (date(2024, 9, 30), "0.00322"),
        (date(2024, 10, 1), "0.00297"), (date(2026, 2, 28), "0.00297"),
        (date(2026, 3, 1), "0.00307"), (date(2030, 1, 1), "0.00307"),
    ],
)  # fmt: skip
def test_the_exchange_transaction_rate_changes_exactly_on_the_dates_zerodha_and_nse_published(
    day, rate
):
    assert comp(day, "EXCHANGE_TRANSACTION").rate_pct == D(rate)


def test_the_rates_that_never_changed_are_the_same_on_every_date():
    for day in (
        date(2016, 1, 1),
        date(2019, 5, 5),
        date(2022, 8, 8),
        date(2025, 6, 2),
        date(2026, 11, 12),
    ):
        assert comp(day, "BROKERAGE").rate_pct == 0
        stt = comp(day, "STT")
        assert (stt.rate_pct, stt.side.value) == (D("0.1"), "BOTH")
        assert comp(day, "SEBI_TURNOVER").rate_pct == D("0.0001")
        stamp = comp(day, "STAMP_DUTY")
        assert (stamp.rate_pct, stamp.side.value) == (D("0.015"), "BUY")


def test_gst_exists_only_from_1_july_2017_and_applies_to_the_sebi_fee_only_from_18_july_2022():
    assert comp(date(2017, 6, 30), "GST") is None and comp(date(2017, 7, 1), "GST").rate_pct == D(
        18
    )
    assert comp(date(2022, 7, 17), "SEBI_TURNOVER").taxable_for_gst is False
    assert comp(date(2022, 7, 18), "SEBI_TURNOVER").taxable_for_gst is True
    assert comp(date(2017, 6, 30), "EXCHANGE_TRANSACTION").taxable_for_gst is False
    assert comp(date(2017, 7, 1), "EXCHANGE_TRANSACTION").taxable_for_gst is True


def test_the_depository_fee_is_13_before_gst_existed_and_15_34_with_gst_after():
    before, after = comp(date(2017, 6, 30), "DP_CHARGE"), comp(date(2017, 7, 1), "DP_CHARGE")
    assert (before.amount, before.gst_inclusive) == (D(13), False)
    assert (after.amount, after.gst_inclusive) == (D("15.34"), True)
    assert comp(date(2024, 10, 1), "DP_CHARGE").amount == D(
        "15.34"
    )  # the split changed, the Rs 13 did not
    assert comp(date(2026, 3, 1), "DP_CHARGE").side.value == "SELL"  # charged when shares are sold


def test_only_evidenced_periods_count_as_extracted_and_the_rest_is_flagged_as_assumed():
    status = {
        d: BOOK.for_date(d).status
        for d in (
            date(2016, 6, 1),
            date(2018, 1, 1),
            date(2021, 1, 1),
            date(2022, 7, 17),
            date(2022, 7, 18),
            date(2025, 1, 1),
            date(2026, 3, 1),
        )
    }
    assert list(status.values()) == ["assumed_backfill"] * 4 + ["extracted_unverified"] * 3
    strict = ScheduleBook(load_schedules(CFG), allowed_statuses=("extracted_unverified",))
    assert strict.coverage("DELIVERY")[0][0] == date(
        2022, 7, 18
    )  # without the assumptions, history starts here
    with pytest.raises(NoScheduleForDate):
        strict.for_date(date(2022, 7, 17))
    for schedule in BOOK.schedules:
        assert schedule.verified_by is None  # nobody has verified any of it yet
        assert all(
            s.url.startswith("https://") and len(s.sha256) == 64 and s.quote
            for s in schedule.sources.values()
        )


@pytest.mark.parametrize(
    ("day", "buy", "sell"),
    [
        (date(2016, 6, 1), "118.55", "116.55"),  # no GST at all; DP Rs 13
        (date(2018, 1, 2), "119.17", "119.51"),  # GST 18% on the exchange fee only (0.18 x 3.45 = 0.621)
        (date(2023, 5, 2), "118.95", "119.29"),  # 0.00325%: txn 3.25, GST 0.18 x (0.10 + 3.25) = 0.603
        (date(2024, 11, 4), "118.62", "118.96"),  # 0.00297%: txn 2.97, GST 0.55
        (date(2026, 3, 2), "118.74", "119.08"),  # 0.00307%: txn 3.07, GST 0.57
    ],
)  # fmt: skip
def test_the_charges_on_a_one_lakh_trade_match_a_hand_calculation_for_every_regime(day, buy, sell):
    schedule = BOOK.for_date(day)
    b = compute_charges(schedule, "BUY", D(1000), D(100))
    s = compute_charges(schedule, "SELL", D(1000), D(100))
    assert (b.total, s.total) == (D(buy), D(sell))
    assert b.amount("STT") == D("100.00") and s.amount("STT") == D("100.00")
    assert (
        b.amount("STAMP_DUTY") == D("15.00") and s.amount("STAMP_DUTY") == 0
    )  # stamp duty on the buy only
    assert b.amount("DP_CHARGE") == 0 and s.amount("DP_CHARGE") in (
        D(13),
        D("15.34"),
    )  # the depository fee on the sell only

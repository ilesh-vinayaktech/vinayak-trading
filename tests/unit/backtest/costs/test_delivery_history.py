# ruff: noqa: E501
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
        (date(2016, 1, 1), "0.00325"), (date(2020, 6, 30), "0.00325"),
        (date(2020, 7, 1), "0.00325"), (date(2020, 12, 31), "0.00325"),
        (date(2021, 1, 1), "0.00345"), (date(2023, 3, 31), "0.00345"),
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


def test_the_depository_fee_is_13_50_until_31_may_2024_then_13_and_includes_gst_only_from_july_2017():
    def dp(day):
        c = comp(day, "DP_CHARGE")
        return c.amount, c.gst_inclusive, c.evidence

    assert dp(date(2017, 6, 30)) == (
        D("13.5"),
        False,
        "ASSUMED",
    )  # Rs 13.50 and service tax, which is not modelled
    assert dp(date(2017, 7, 1)) == (D("15.93"), True, "ASSUMED")  # Rs 13.50 + 18% GST
    assert dp(date(2024, 5, 31)) == (D("15.93"), True, "ASSUMED")
    assert dp(date(2024, 6, 1)) == (
        D("15.34"),
        True,
        "ASSUMED",
    )  # Rs 13 + GST: the reported CDSL reduction, not a dated notice
    assert dp(date(2024, 9, 30)) == (D("15.34"), True, "ASSUMED")
    assert dp(date(2024, 10, 1))[2] == "EXTRACTED_UNVERIFIED" and dp(date(2024, 10, 1))[0] == D(
        "15.34"
    )  # Zerodha's bulletin evidences Rs 13
    assert comp(date(2026, 3, 1), "DP_CHARGE").side.value == "SELL"  # charged when shares are sold


def test_assumed_components_are_labelled_where_the_evidence_stops_and_name_what_is_taken_on_trust():
    def assumed(day):
        return sorted(c.type for c in BOOK.for_date(day).components if c.evidence == "ASSUMED")

    both = ["DP_CHARGE", "EXCHANGE_TRANSACTION", "STAMP_DUTY"]
    assert (
        assumed(date(2016, 6, 1)) == both and assumed(date(2018, 1, 1)) == both
    )  # state stamp duty, unevidenced client fee, DP
    assert assumed(date(2020, 9, 1)) == [
        "DP_CHARGE",
        "EXCHANGE_TRANSACTION",
    ]  # stamp duty is uniform from 1 Jul 2020
    for day in (
        date(2021, 1, 1),
        date(2022, 7, 18),
        date(2023, 5, 1),
        date(2024, 5, 31),
        date(2024, 6, 1),
        date(2024, 9, 30),
    ):
        assert assumed(day) == ["DP_CHARGE"]  # Rs 13 is evidenced only for just before Oct 2024
    for day in (date(2024, 10, 1), date(2025, 6, 1), date(2026, 3, 1)):
        assert assumed(day) == []
    listed = {
        d: BOOK.for_date(d).assumptions
        for d in (
            date(2016, 6, 1),
            date(2018, 1, 1),
            date(2020, 9, 1),
            date(2021, 6, 1),
            date(2022, 8, 1),
        )
    }
    assert [len(v) for v in listed.values()] == [4, 3, 2, 2, 1]
    assert not BOOK.for_date(date(2025, 1, 1)).assumptions
    joined = " ".join(" ".join(v) for v in listed.values())
    for topic in (
        "Stamp duty before 1 July 2020",
        "Service tax",
        "MEMBER tariff",
        "0.00325%",
        "1 January 2021",
        "depository charge",
        "Rs 13.50",
    ):
        assert topic in joined, (
            topic
        )  # each thing taken on trust is stated, in words a verifier can read
    for schedule in BOOK.schedules:
        if schedule.product != "DELIVERY":
            continue
        assert (
            schedule.status == "extracted_unverified" and schedule.verified_by is None
        )  # nobody has verified any of it
        assert schedule.account_scope == "RESIDENT_INDIVIDUAL_RETAIL"
        assert all(
            x.url.startswith("https://") and len(x.sha256) == 64 and x.quote
            for x in schedule.sources.values()
        )


# a BUY of 1,000 shares at Rs 100 (Rs 1 lakh), worked by hand on each side of every change of rule: STT 100.00, SEBI 0.10, stamp 15.00,
# the exchange fee, and 18% GST on (exchange fee, plus the SEBI fee from 18 Jul 2022); a SELL has no stamp duty and pays the depository fee
@pytest.mark.parametrize(
    ("day", "buy", "dp"),
    [
        (date(2017, 6, 30), "118.35", "13.5"),   # no GST yet; exchange fee 3.25 (assumed)
        (date(2017, 7, 1), "118.94", "15.93"),   # GST 0.585 rounds half-up to 0.59; DP Rs 13.50 + GST
        (date(2020, 6, 30), "118.94", "15.93"),
        (date(2020, 7, 1), "118.94", "15.93"),   # same assumed 3.25 on both sides of 1 Jul 2020 (stamp duty is 0.015% in both)
        (date(2020, 12, 31), "118.94", "15.93"),
        (date(2021, 1, 1), "119.17", "15.93"),   # NSE/FA/46730: 3.45, GST 0.621
        (date(2022, 7, 17), "119.17", "15.93"),
        (date(2022, 7, 18), "119.19", "15.93"),  # SEBI fee now in the GST base: 0.18 x (3.45 + 0.10) = 0.639
        (date(2023, 3, 31), "119.19", "15.93"),
        (date(2023, 4, 1), "118.95", "15.93"),   # 3.25: 0.18 x 3.35 = 0.603
        (date(2024, 3, 31), "118.95", "15.93"),
        (date(2024, 4, 1), "118.92", "15.93"),   # 3.22: 0.18 x 3.32 = 0.5976
        (date(2024, 5, 31), "118.92", "15.93"),
        (date(2024, 6, 1), "118.92", "15.34"),   # DP Rs 13 + GST, nothing else changes
        (date(2024, 9, 30), "118.92", "15.34"),
        (date(2024, 10, 1), "118.62", "15.34"),  # 2.97: 0.18 x 3.07 = 0.5526
        (date(2026, 2, 28), "118.62", "15.34"),
        (date(2026, 3, 1), "118.74", "15.34"),   # 3.07: 0.18 x 3.17 = 0.5706
    ],
)  # fmt: skip
def test_the_charge_on_a_one_lakh_trade_changes_exactly_on_the_day_each_rule_changes(day, buy, dp):
    schedule = BOOK.for_date(day)
    b, s = (
        compute_charges(schedule, "BUY", D(1000), D(100)),
        compute_charges(schedule, "SELL", D(1000), D(100)),
    )
    assert b.total == D(buy)
    assert s.total == D(buy) - D(15) + D(dp)  # no stamp duty on a sale, and the depository fee


@pytest.mark.parametrize(
    ("day", "buy", "sell"),
    [
        (date(2016, 6, 1), "118.35", "116.85"),  # no GST at all; exchange fee 3.25 (assumed), DP Rs 13.50
        (date(2018, 1, 2), "118.94", "119.87"),  # GST 18% on the exchange fee only (0.18 x 3.25 = 0.585); DP 15.93
        (date(2023, 5, 2), "118.95", "119.88"),  # 0.00325%: txn 3.25, GST 0.18 x (0.10 + 3.25) = 0.603
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
        D("13.5"),
        D("15.93"),
        D("15.34"),
    )  # the depository fee on the sell only

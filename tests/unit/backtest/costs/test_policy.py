from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.policy import PLACEHOLDER_COSTS, CostModel, Liquidity, ScheduleCosts
from algo.backtest.costs.schedule import NoScheduleForDate, ScheduleBook, load_schedules
from algo.backtest.costs.slippage import SlippageModel

CFG = Path(__file__).parents[4] / "config/cost_schedules"
LIQ = Liquidity(volume=D(10_000), range_bps=D(200), adv_value=D(50_000_000))
DAY_OLD, DAY_NEW = (
    date(2021, 3, 9),
    date(2026, 6, 1),
)  # a date still in an assumed period; one in the current schedule


def costs(statuses=("assumed_backfill", "extracted_unverified"), slippage=None, product="DELIVERY"):
    book = ScheduleBook(load_schedules(CFG), allowed_statuses=statuses)
    return ScheduleCosts(book, slippage if slippage is not None else SlippageModel(), product)


# ---- the flat placeholder -------------------------------------------------------------------
def test_flat_costs_are_one_exact_commission_line_and_flagged_as_placeholder():
    m = CostModel("t", D(10), D(5), False)
    ch = m.charges(DAY_OLD, "BUY", D(99), D("100.05"))
    (line,) = ch.lines
    assert (line.type, line.amount, line.basis_value) == ("COMMISSION", D("9.90495"), D("9904.95"))
    assert line.formula == "10 bps of 9904.95" and ch.schedule_status == "placeholder"
    assert ch.amount("COMMISSION") == ch.total == D("9.90495")
    assert PLACEHOLDER_COSTS.placeholder and PLACEHOLDER_COSTS.name == "flat-bps-placeholder"


def test_flat_fill_applies_a_constant_slippage_each_way_and_never_tops_up():
    m = CostModel("t", D(10), D(5), False)
    assert m.fill("BUY", D(100), D(1), LIQ) == (D("100.05"), D(5))
    assert m.fill("SELL", D(100), D(1), LIQ) == (D("99.95"), D(5))
    assert m.note_shortfall(DAY_OLD, D(0)) == 0
    assert m.describe() == {
        "kind": "flat_bps", "name": "t", "placeholder": False, "commission_bps": "10",
        "slippage_bps": "5", "zero_slippage": False,
    }  # fmt: skip
    assert not m.zero_slippage and CostModel("z", D(0), D(0), False).zero_slippage


# ---- schedule-based costs -------------------------------------------------------------------
def test_schedule_costs_pick_the_schedule_in_force_on_the_trade_date():
    c = costs()
    old, new = (
        c.charges(DAY_OLD, "BUY", D(100), D(1000)),
        c.charges(DAY_NEW, "BUY", D(100), D(1000)),
    )
    assert (old.schedule_status, new.schedule_status) == (
        "extracted_unverified",
        "extracted_unverified",
    )
    assert (
        old.schedule_id == "nse-cash-delivery-zerodha-2021-01-01"
        and new.schedule_id == "nse-cash-delivery-zerodha-2026-03-01"
    )
    assert c.charges(DAY_NEW, "BUY", D(100), D(1000)).total == D("118.74")


def test_a_date_with_no_usable_schedule_stops_the_run_instead_of_guessing():
    with pytest.raises(NoScheduleForDate):
        costs(statuses=("verified",)).charges(DAY_NEW, "BUY", D(1), D(100))
    with pytest.raises(NoScheduleForDate):
        costs(statuses=("assumed_backfill",)).charges(
            DAY_OLD, "BUY", D(1), D(100)
        )  # no delivery period is merely assumed now
    with pytest.raises(NoScheduleForDate):
        costs().charges(date(2015, 12, 31), "BUY", D(1), D(100))  # before the history starts


def test_slippage_uses_the_orders_share_of_the_bars_volume():
    c = costs(slippage=SlippageModel(base_bps=D(5), participation_bps_per_pct=D(2)))
    # 100 of 10,000 shares = 1% participation => 5 + 1 x 2 = 7 bps
    price, bps = c.fill("BUY", D(100), D(100), LIQ)
    assert bps == D(7) and price == D("100.07")
    price, bps = c.fill("SELL", D(100), D(100), LIQ)
    assert bps == D(7) and price == D("99.93")


def test_contract_note_top_up_comes_from_the_schedule_in_force():
    c = costs()
    assert c.note_shortfall(DAY_OLD, D("0")) == D("0.01")
    assert c.note_shortfall(DAY_OLD, D("0.01")) == 0
    with pytest.raises(NoScheduleForDate):
        costs(statuses=("verified",)).note_shortfall(DAY_OLD, D(0))
    assert costs(product="INTRADAY").note_shortfall(DAY_OLD, D(0)) == 0


def test_describe_records_the_model_so_a_run_can_be_judged_later():
    d = costs(slippage=SlippageModel(base_bps=D(5), max_bps=D(50))).describe()
    assert d["kind"] == "schedule" and d["placeholder"] is False and d["product"] == "DELIVERY"
    assert d["allowed_statuses"] == ["assumed_backfill", "extracted_unverified"]
    assert (
        d["legacy_verified"] == []
    )  # nothing in the committed book was verified before components carried evidence
    assert d["coverage"] == [
        ["2016-01-01", "2017-06-30"],
        ["2017-07-01", "2020-05-31"],
        ["2020-06-01", "2020-06-30"],
        ["2020-07-01", "2020-12-31"],
        ["2021-01-01", "2021-03-31"],
        ["2021-04-01", "2022-07-17"],
        ["2022-07-18", "2023-03-31"],
        ["2023-04-01", "2024-03-31"],
        ["2024-04-01", "2024-05-31"],
        ["2024-06-01", "2024-09-30"],
        ["2024-10-01", "2026-02-28"],
        ["2026-03-01", None],
    ]
    assert d["slippage"]["base_bps"] == "5" and d["slippage"]["max_bps"] == "50"
    assert d["zero_slippage"] is False and costs().describe()["zero_slippage"] is True
    assert costs().zero_slippage and not costs(slippage=SlippageModel(base_bps=D(1))).zero_slippage


# ---- gaps found by mutation testing ------------------------------------------------------------
def test_flat_costs_record_who_and_what_on_every_charge():
    m = CostModel("t", D(10), D(5), False)
    ch = m.charges(DAY_OLD, "SELL", D(10), D(100))
    (line,) = ch.lines
    assert (line.rounding, line.source) == ("NONE", "t")
    assert (ch.side, ch.schedule_id, ch.schedule_version, ch.schedule_status) == (
        "SELL",
        "t",
        "1",
        "placeholder",
    )


def test_the_product_selects_which_schedule_prices_the_order():
    delivery = costs(product="DELIVERY").charges(DAY_OLD, "BUY", D(100), D(1000))
    intraday = costs(product="INTRADAY").charges(DAY_OLD, "BUY", D(100), D(1000))
    assert (
        delivery.schedule_id.startswith("nse-cash-delivery") and delivery.amount("BROKERAGE") == 0
    )
    assert intraday.schedule_id.startswith("nse-cash-intraday") and intraday.amount(
        "BROKERAGE"
    ) == D("20.00")


def test_the_illiquidity_surcharge_reads_the_orders_liquidity():
    m = SlippageModel(illiquid_adv_threshold=D(10_000_000), illiquid_extra_bps=D(9))
    c = costs(slippage=m)
    assert c.fill("BUY", D(100), D(1), Liquidity(D(10_000), D(0), D(50_000_000)))[1] == 0
    assert c.fill("BUY", D(100), D(1), Liquidity(D(10_000), D(0), D(5_000_000)))[1] == D(9)
    assert c.fill("BUY", D(100), D(1), Liquidity(D(10_000), D(0), None))[1] == D(9)


def test_describe_lists_exactly_what_was_configured():
    m = SlippageModel(base_bps=D(5))
    d = costs(slippage=m, statuses=("assumed_backfill",)).describe()
    assert d == {
        "kind": "schedule", "name": "schedule-costs", "placeholder": False, "product": "DELIVERY",
        "allowed_statuses": ["assumed_backfill"], "legacy_verified": [], "coverage": [],
        "slippage": {
            "base_bps": "5", "participation_bps_per_pct": "0", "volatility_fraction": "0",
            "illiquid_adv_threshold": "None", "illiquid_extra_bps": "0", "max_bps": "1000",
        },
        "zero_slippage": False,
    }  # fmt: skip

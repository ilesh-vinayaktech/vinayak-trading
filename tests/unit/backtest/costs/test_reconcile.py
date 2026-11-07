from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.policy import ScheduleCosts
from algo.backtest.costs.reconcile import reconcile_note
from algo.backtest.costs.schedule import ScheduleBook, load_schedules
from algo.backtest.costs.slippage import SlippageModel

CFG = Path(__file__).parents[4] / "config/cost_schedules"
DAY = date(2026, 6, 1)
COSTS = ScheduleCosts(
    ScheduleBook(load_schedules(CFG), allowed_statuses=("extracted_unverified",)), SlippageModel()
)
# one delivery buy of 100 @ 1000 -> the hand-computed charges from test_calculator
BUY = [("BUY", D(100), D(1000))]
NOTE = {
    "BROKERAGE": D("0.01"),  # the delivery contract-note minimum
    "STT": D("100.00"),
    "EXCHANGE_TRANSACTION": D("3.07"),
    "SEBI_TURNOVER": D("0.10"),
    "STAMP_DUTY": D("15.00"),
    "GST": D("0.57"),
}


def test_a_note_that_matches_reconciles_exactly():
    r = reconcile_note(COSTS, DAY, BUY, NOTE)
    assert (
        r.ok and r.rounding_only == () and r.discrepancies == () and r.orders == 1 and r.day == DAY
    )


def test_paisa_rounding_differences_are_reported_but_allowed():
    r = reconcile_note(
        COSTS, DAY, BUY, {**NOTE, "GST": D("0.58"), "EXCHANGE_TRANSACTION": D("3.06")}
    )
    assert r.ok and {d.type for d in r.rounding_only} == {"GST", "EXCHANGE_TRANSACTION"}
    gst = next(d for d in r.rounding_only if d.type == "GST")
    assert (gst.computed, gst.reported, gst.delta) == (D("0.57"), D("0.58"), D("-0.01"))


def test_anything_beyond_rounding_is_a_discrepancy():
    r = reconcile_note(COSTS, DAY, BUY, {**NOTE, "STT": D("100.02")})
    assert not r.ok and [d.type for d in r.discrepancies] == ["STT"]
    assert r.discrepancies[0].delta == D("-0.02")


def test_the_rounding_allowance_grows_with_the_number_of_orders():
    two = BUY + BUY
    doubled = {k: v * 2 for k, v in NOTE.items()} | {"BROKERAGE": D("0.01")}
    r = reconcile_note(COSTS, DAY, two, {**doubled, "STT": D("200.02")})
    assert r.ok and r.allowed == D("0.02")  # 2 orders x 0.01
    assert not reconcile_note(COSTS, DAY, two, {**doubled, "STT": D("200.03")}).ok


def test_a_component_on_only_one_side_is_a_discrepancy_even_if_tiny():
    extra = reconcile_note(COSTS, DAY, BUY, {**NOTE, "DP_CHARGE": D("0.01")})
    assert not extra.ok and extra.discrepancies[0].type == "DP_CHARGE"
    missing = {k: v for k, v in NOTE.items() if k != "STAMP_DUTY"}
    r = reconcile_note(COSTS, DAY, BUY, missing)
    assert not r.ok and r.discrepancies[0].type == "STAMP_DUTY"
    assert r.discrepancies[0].computed == D("15.00") and r.discrepancies[0].reported == 0


def test_a_sell_with_the_dp_charge_and_a_buy_on_one_note():
    orders = BUY + [("SELL", D(100), D(1100))]
    note = {
        "BROKERAGE": D("0.01"), "STT": D("210.00"), "EXCHANGE_TRANSACTION": D("6.45"),
        "SEBI_TURNOVER": D("0.21"), "STAMP_DUTY": D("15.00"), "DP_CHARGE": D("15.34"),
        "GST": D("1.20"),
    }  # fmt: skip
    r = reconcile_note(COSTS, DAY, orders, note)
    assert r.ok and r.rounding_only == ()


def test_a_note_needs_orders():
    with pytest.raises(ValueError, match="^a contract note needs at least one order$"):
        reconcile_note(COSTS, DAY, [], NOTE)


def test_an_intraday_note_has_no_minimum_brokerage_top_up():
    intraday = ScheduleCosts(COSTS.book, SlippageModel(), "INTRADAY")
    note = {  # buy 100 @ 1000 (hand-computed in test_calculator)
        "BROKERAGE": D("20.00"), "EXCHANGE_TRANSACTION": D("3.07"), "SEBI_TURNOVER": D("0.10"),
        "STAMP_DUTY": D("3.00"), "GST": D("4.17"),
    }  # fmt: skip
    r = reconcile_note(intraday, DAY, BUY, note)
    assert r.ok and r.rounding_only == ()
    assert not reconcile_note(
        intraday, DAY, BUY, {**note, "BROKERAGE": D("20.01")} | {"STT": D("1")}
    ).ok


def _tiny_brokerage_costs():
    import copy
    import json

    from algo.backtest.costs.schedule import schedule_from_dict

    d = copy.deepcopy(json.loads((CFG / "nse_cash_zerodha.json").read_text())["schedules"][0])
    d["components"][0].update(rate_pct="0.000004", rounding="NONE")  # BROKERAGE: 0.004 on 1,00,000
    return ScheduleCosts(
        ScheduleBook([schedule_from_dict(d)], allowed_statuses=("extracted_unverified",)),
        SlippageModel(),
    )


def test_brokerage_accumulates_over_the_notes_orders_before_the_minimum_is_applied():
    c = (
        _tiny_brokerage_costs()
    )  # each order: 0.004 brokerage; two orders: 0.008; floor 0.01 -> top-up 0.002
    orders = [("BUY", D(100), D(1000)), ("BUY", D(100), D(1000))]
    ch = c.charges(DAY, "BUY", D(100), D(1000))
    two = {  # two identical buys, with BROKERAGE brought up to exactly the 0.01 floor
        "BROKERAGE": D("0.010"), "STT": D("200.00"), "EXCHANGE_TRANSACTION": D("6.14"),
        "SEBI_TURNOVER": D("0.20"), "STAMP_DUTY": D("30.00"), "GST": D("1.14"),
    }  # fmt: skip
    assert ch.amount("BROKERAGE") == D("0.004")
    r = reconcile_note(c, DAY, orders, two)
    assert r.ok and not [d for d in r.discrepancies + r.rounding_only if d.type == "BROKERAGE"]


def test_a_component_reported_as_zero_on_one_side_only_is_not_a_discrepancy():
    r = reconcile_note(COSTS, DAY, BUY, {**NOTE, "DP_CHARGE": D(0)})  # a buy has no DP charge
    assert r.ok and r.discrepancies == () and r.rounding_only == ()

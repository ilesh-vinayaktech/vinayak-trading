from decimal import Decimal as D
from pathlib import Path

import pytest

from algo.backtest.costs.calculator import compute_charges, contract_note_shortfall
from algo.backtest.costs.schedule import load_schedules

CFG = Path(__file__).parents[4] / "config/cost_schedules"
SCHEDULES = {s.id: s for s in load_schedules(CFG, pattern="nse_cash_zerodha.json")}
DELIVERY = SCHEDULES["nse-cash-delivery-zerodha-2026-03-01"]
INTRADAY = SCHEDULES["nse-cash-intraday-zerodha-2026-03-01"]


def amounts(c):
    return {ln.type: ln.amount for ln in c.lines}


# ---- hand-computed worked orders (rates are the ones in the committed, quoted schedules) -----
def test_delivery_buy_100_at_1000():
    c = compute_charges(DELIVERY, "BUY", D(100), D(1000))  # value 1,00,000
    assert amounts(c) == {
        "BROKERAGE": D("0.00"),
        "STT": D("100.00"),  # 0.1%
        "EXCHANGE_TRANSACTION": D("3.07"),  # 0.00307%
        "SEBI_TURNOVER": D("0.10"),  # 0.0001%
        "STAMP_DUTY": D("15.00"),  # 0.015%, buy side
        "GST": D("0.57"),  # 18% x (0 + 3.07 + 0.10) = 0.5706
    }
    assert c.total == D("118.74") and "DP_CHARGE" not in amounts(c)


def test_delivery_sell_100_at_1100_carries_the_dp_charge_and_no_stamp_duty():
    c = compute_charges(DELIVERY, "SELL", D(100), D(1100))  # value 1,10,000
    assert amounts(c) == {
        "BROKERAGE": D("0.00"),
        "STT": D("110.00"),
        "EXCHANGE_TRANSACTION": D("3.38"),  # 3.377 rounded half-up
        "SEBI_TURNOVER": D("0.11"),
        "DP_CHARGE": D("15.34"),  # flat per scrip, already includes its GST
        "GST": D("0.63"),  # 18% x (0 + 3.38 + 0.11) = 0.6282
    }
    assert c.total == D("129.46")


def test_intraday_buy_brokerage_is_capped_at_twenty_rupees():
    c = compute_charges(INTRADAY, "BUY", D(100), D(1000))
    assert amounts(c) == {
        "BROKERAGE": D("20.00"),  # 0.03% = 30, capped at 20 per executed order
        "EXCHANGE_TRANSACTION": D("3.07"),
        "SEBI_TURNOVER": D("0.10"),
        "STAMP_DUTY": D("3.00"),  # 0.003%, buy side
        "GST": D("4.17"),  # 18% x (20 + 3.07 + 0.10) = 4.1706
    }
    assert c.total == D("30.34")


def test_intraday_sell_has_stt_and_no_stamp_duty():
    c = compute_charges(INTRADAY, "SELL", D(100), D(1010))
    assert amounts(c) == {
        "BROKERAGE": D("20.00"),
        "STT": D("25.25"),  # 0.025%, sell side
        "EXCHANGE_TRANSACTION": D("3.10"),
        "SEBI_TURNOVER": D("0.10"),
        "GST": D("4.18"),  # 18% x (20 + 3.10 + 0.10) = 4.176
    }
    assert c.total == D("52.63")


def test_below_the_cap_the_percentage_applies():
    c = compute_charges(INTRADAY, "BUY", D(100), D(200))  # value 20,000: 0.03% = 6.00 < 20
    assert c.amount("BROKERAGE") == D("6.00")


def test_every_line_can_be_explained():
    c = compute_charges(INTRADAY, "BUY", D(100), D(1000))
    brokerage = next(ln for ln in c.lines if ln.type == "BROKERAGE")
    assert (
        brokerage.basis_value == D(100000)
        and brokerage.formula == "0.03% of 100000, capped at maximum 20"
    )
    assert brokerage.source == "zerodha_brokerage_intraday" and brokerage.rounding == "HALF_UP_2DP"
    gst = next(ln for ln in c.lines if ln.type == "GST")
    assert gst.basis_value == D("23.17") and gst.formula == "18% of GST base 23.17"
    assert (c.schedule_id, c.schedule_version, c.schedule_status) == (
        INTRADAY.id, INTRADAY.version, "extracted_unverified"
    )  # fmt: skip
    stt = next(
        ln for ln in compute_charges(INTRADAY, "SELL", D(1), D(100)).lines if ln.type == "STT"
    )
    assert stt.formula == "0.025% of 100" and stt.basis_value == D(100)


def test_the_dp_charge_is_not_in_the_gst_base_because_it_already_includes_gst():
    c = compute_charges(DELIVERY, "SELL", D(1), D(100))
    gst = next(ln for ln in c.lines if ln.type == "GST")
    assert gst.basis_value == D("0.00") + c.amount("EXCHANGE_TRANSACTION") + c.amount(
        "SEBI_TURNOVER"
    )
    dp = next(ln for ln in c.lines if ln.type == "DP_CHARGE")
    assert dp.basis_value is None and dp.formula == "flat 15.34 per scrip"


def test_charges_are_additive_and_totals_match_the_lines():
    c = compute_charges(DELIVERY, "SELL", D(7), D("233.45"))
    assert c.total == sum((ln.amount for ln in c.lines), D(0)) and c.amount("STT") > 0
    assert c.amount("NOPE") == 0


@pytest.mark.parametrize(
    "side,qty,price",
    [("HOLD", D(1), D(1)), ("BUY", D(0), D(1)), ("BUY", D(1), D(0)), ("SELL", D(-1), D(5))],
)
def test_nonsense_orders_are_rejected(side, qty, price):
    with pytest.raises(ValueError):
        compute_charges(DELIVERY, side, qty, price)


def test_side_message():
    with pytest.raises(ValueError, match="^side must be BUY or SELL$"):
        compute_charges(DELIVERY, "X", D(1), D(1))


# ---- contract-note minimum brokerage ---------------------------------------------------------
def test_delivery_contract_note_minimum_tops_up_only_the_shortfall():
    assert contract_note_shortfall(DELIVERY, D("0.00")) == D("0.01")
    assert contract_note_shortfall(DELIVERY, D("0.01")) == 0
    assert contract_note_shortfall(DELIVERY, D("5")) == 0
    assert contract_note_shortfall(INTRADAY, D("0")) == 0  # intraday has no such minimum


# ---- rounding and boundaries ----------------------------------------------------------------
def test_half_up_rounding_at_the_paisa_boundary():
    # SEBI 0.0001% of 5,00,000 = 0.5 -> 0.50 ; of 5,50,000 = 0.55 ; value 1,05,000 -> 0.105 -> 0.11 (half-up)
    assert compute_charges(DELIVERY, "BUY", D(1), D(105000)).amount("SEBI_TURNOVER") == D("0.11")
    assert compute_charges(DELIVERY, "BUY", D(1), D(104999)).amount("SEBI_TURNOVER") == D("0.10")


def test_a_sub_rupee_trade_still_produces_valid_lines():
    c = compute_charges(DELIVERY, "BUY", D(1), D("0.5"))
    assert c.amount("STT") == D("0.00") and c.total >= 0


# ---- component minimum / rounding options ---------------------------------------------------
def schedule_with(index, **changes):
    import copy
    import json

    from algo.backtest.costs.schedule import schedule_from_dict

    d = copy.deepcopy(json.loads((CFG / "nse_cash_zerodha.json").read_text())["schedules"][0])
    d["components"][index].update(changes)
    return schedule_from_dict(d)


def test_a_component_minimum_raises_a_small_charge_and_says_so():
    s = schedule_with(0, rate_pct="0.01", minimum="5")  # BROKERAGE 0.01% of 1,000 = 0.10 -> 5
    line = next(
        ln for ln in compute_charges(s, "BUY", D(1), D(1000)).lines if ln.type == "BROKERAGE"
    )
    assert line.amount == D("5.00") and line.formula == "0.01% of 1000, raised to minimum 5"
    big = next(
        ln for ln in compute_charges(s, "BUY", D(1), D(100000)).lines if ln.type == "BROKERAGE"
    )
    assert big.amount == D("10.00") and "minimum" not in big.formula  # 0.01% of 1,00,000 > 5


def test_a_component_with_no_rounding_keeps_full_precision():
    s = schedule_with(1, rounding="NONE")  # STT 0.1%, unrounded
    c = compute_charges(s, "BUY", D(3), D("123.45"))
    assert c.amount("STT") == D("0.37035") and c.lines[1].rounding == "NONE"


# ---- gaps found by mutation testing ------------------------------------------------------------
def test_every_line_cites_its_source_rounding_and_the_side_is_recorded():
    c = compute_charges(DELIVERY, "SELL", D(100), D(1100))
    assert c.side == "SELL"
    assert {ln.type: ln.source for ln in c.lines} == {
        "BROKERAGE": "zerodha_brokerage_delivery",
        "STT": "zerodha_stt_delivery",
        "EXCHANGE_TRANSACTION": "zerodha_nse_transaction",
        "SEBI_TURNOVER": "zerodha_sebi",
        "DP_CHARGE": "zerodha_dp_charge",
        "GST": "zerodha_gst",
    }
    assert {ln.rounding for ln in c.lines} == {"HALF_UP_2DP"}
    assert compute_charges(DELIVERY, "BUY", D(1), D(100)).side == "BUY"


def test_a_flat_per_executed_order_charge_says_so():
    s = schedule_with(
        5, basis="PER_EXECUTED_ORDER", rate_pct=None, amount="7.50", side="BOTH"
    )  # DP slot
    line = next(
        ln for ln in compute_charges(s, "BUY", D(1), D(100)).lines if ln.type == "DP_CHARGE"
    )
    assert line.amount == D("7.50") and line.formula == "flat 7.50 per executed order"


def test_minimum_and_maximum_exactly_met_do_not_claim_to_have_been_applied():
    s = schedule_with(
        0, rate_pct="1", minimum="10", maximum="10"
    )  # BROKERAGE 1% clamped to exactly 10
    on_min = next(
        ln for ln in compute_charges(s, "BUY", D(1), D(1000)).lines if ln.type == "BROKERAGE"
    )
    assert (
        on_min.amount == D("10.00") and on_min.formula == "1% of 1000"
    )  # 1% of 1000 == 10 exactly
    s2 = schedule_with(0, rate_pct="1", maximum="10")
    on_max = next(
        ln for ln in compute_charges(s2, "BUY", D(1), D(1000)).lines if ln.type == "BROKERAGE"
    )
    assert on_max.formula == "1% of 1000" and "capped" not in on_max.formula


def test_contract_note_shortfall_is_the_exact_gap_to_the_floor():
    assert contract_note_shortfall(DELIVERY, D("0.004")) == D("0.006")
    assert contract_note_shortfall(DELIVERY, D("0.0099")) == D("0.0001")

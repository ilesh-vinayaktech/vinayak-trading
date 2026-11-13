from datetime import date
from decimal import Decimal as D

from algo.backtest.report import build_report

# (seq, day, instrument_id, side, qty, price, charges)
BUY1 = (1, date(2024, 1, 1), 7, "BUY", D(10), D(100), D(2))
BUY2 = (2, date(2024, 1, 11), 7, "BUY", D(10), D(120), D(2))
SELL = (3, date(2024, 2, 1), 7, "SELL", D(15), D(130), D(3))
NAMES = {7: "ABC", 8: "XYZ"}


def rep(fills, equity=None, cash=D(10000)):
    eq = equity or [(date(2024, 1, 1), cash), (date(2024, 3, 1), D(10500))]
    return build_report(fills, eq, cash, NAMES)


def test_sell_closes_oldest_lots_first_and_splits_charges_by_quantity():
    r = rep([BUY1, BUY2, SELL])
    a, b = r["round_trips"]
    # 10 @100 -> 130: gross 300; charges 2 (buy) + 3*10/15 = 2 (sell) -> net 296
    assert (a["symbol"], a["qty"], a["gross"], a["charges"], a["net"]) == (
        "ABC",
        "10",
        "300",
        "4",
        "296",
    )
    assert a["holding_days"] == 31
    # 5 @120 -> 130: gross 50; charges 2*5/10 = 1 + 1 -> net 48
    assert (b["qty"], b["gross"], b["charges"], b["net"]) == ("5", "50", "2", "48")


def test_unsold_shares_are_open_positions_not_trades():
    r = rep([BUY1, BUY2, SELL])
    assert r["open_positions"] == [
        {
            "symbol": "ABC",
            "instrument_id": 7,
            "qty": "5",
            "lots": 1,
            "entry_day": "2024-01-11",
            "entry_price": "120",
        }
    ]
    assert r["summary"]["trades"] == 2


def test_summary_and_headline():
    r = rep([BUY1, BUY2, SELL])
    s = r["summary"]
    assert (s["net_pnl"], s["charges"], s["wins"], s["losses"], s["win_rate"]) == (
        "344",
        "6",
        2,
        0,
        "1.0000",
    )
    assert s["profit_factor"] is None  # no losing trade: undefined, not infinite
    h = r["headline"]
    assert (h["initial"], h["final"], h["change"], h["return"]) == (
        "10000",
        "10500",
        "500",
        "0.0500",
    )


def test_loss_and_by_stock():
    fills = [BUY1, (2, date(2024, 1, 5), 7, "SELL", D(10), D(90), D(2)),
             (3, date(2024, 1, 6), 8, "BUY", D(1), D(50), D(1)), (4, date(2024, 1, 9), 8, "SELL", D(1), D(60), D(1))]  # fmt: skip
    r = rep(fills)
    s = r["summary"]
    assert (s["wins"], s["losses"], s["net_pnl"], s["profit_factor"]) == (1, 1, "-96", "0.0769")
    assert (s["avg_win"], s["avg_loss"]) == ("8", "-104")
    by = {x["symbol"]: x for x in r["by_stock"]}
    assert (by["ABC"]["net"], by["ABC"]["trades"], by["ABC"]["win_rate"]) == ("-104", 1, "0.0000")
    assert by["XYZ"]["net"] == "8"


def test_a_sell_with_nothing_held_is_skipped_not_crashed():
    r = rep([(1, date(2024, 1, 1), 7, "SELL", D(5), D(100), D(1))])
    assert (
        r["round_trips"] == [] and r["summary"]["trades"] == 0 and r["summary"]["win_rate"] is None
    )


def test_empty_curve_has_no_headline_change():
    r = build_report([], [], D(100), NAMES)
    assert r["headline"]["final"] is None and r["curve"] == []


def test_curve_is_drawdown_aware():
    r = rep([], [(date(2024, 1, 1), D(100)), (date(2024, 1, 2), D(120)), (date(2024, 1, 3), D(90))])
    assert [p["drawdown"] for p in r["curve"]] == ["0.0000", "0.0000", "-0.2500"]
    assert r["headline"]["max_drawdown"] == "-0.2500"


def test_monthly_weekday_and_distribution_views():
    f = [
        (1, date(2024, 1, 1), 7, "BUY", D(10), D(100), D(0)),
        (2, date(2024, 1, 5), 7, "SELL", D(10), D(105), D(0)),  # Fri, +5% -> +50
        (3, date(2024, 1, 8), 7, "BUY", D(10), D(100), D(0)),
        (4, date(2024, 2, 7), 7, "SELL", D(10), D(80), D(0)),  # Wed, -20% -> -200
    ]
    r = rep(f)
    assert r["monthly"] == [
        {"month": "2024-01", "net": "50", "trades": 1},
        {"month": "2024-02", "net": "-200", "trades": 1},
    ]
    wd = {w["weekday"]: w for w in r["by_weekday"]}
    assert (wd["Fri"]["net"], wd["Fri"]["trades"], wd["Wed"]["net"], wd["Mon"]["trades"]) == (
        "50",
        1,
        "-200",
        0,
    )
    bins = {b["label"]: b["count"] for b in r["distribution"]}
    assert bins["4% to 6%"] == 1 and bins["below -10%"] == 1 and sum(bins.values()) == 2
    assert len(r["distribution"]) == 12


def test_views_are_empty_without_trades():
    r = rep([])
    assert r["monthly"] == [] and sum(b["count"] for b in r["distribution"]) == 0


def test_several_lots_of_one_stock_are_one_open_position_at_the_average_price():
    r = rep([BUY1, BUY2])  # 10 @ 100 and 10 @ 120, nothing sold
    assert r["open_positions"] == [
        {
            "symbol": "ABC",
            "instrument_id": 7,
            "qty": "20",
            "lots": 2,
            "entry_day": "2024-01-01",
            "entry_price": "110",
        }
    ]


def curve_of(*vals, start=date(2024, 1, 1)):
    from datetime import timedelta

    return [(start + timedelta(days=i), D(v)) for i, v in enumerate(vals)]


def test_the_index_is_rebased_to_the_start_amount_and_compared_on_the_same_days():
    eq = curve_of(10000, 11000, 9900)  # +10%, -10%: ends -1%, worst drop -10%
    idx = {d: D(v) for (d, _), v in zip(eq, (200, 220, 231), strict=True)}  # +10%, +5%
    r = build_report([], eq, D(10000), NAMES, ("Nifty 200 TRI", idx))
    b = r["benchmark"]
    assert (b["name"], b["note"], b["return"], b["final"], b["max_drawdown"]) == (
        "Nifty 200 TRI", None, "0.1550", "11550", "0.0000"
    )  # fmt: skip
    assert [p["level"] for p in b["curve"]] == ["10000", "11000", "11550"]
    assert b["strategy_return"] == "-0.0100" and b["strategy_max_drawdown"] == "-0.1000"
    assert b["sharpe"] is not None and b["strategy_sharpe"] is not None


def test_an_index_that_misses_a_day_is_not_used_and_says_why():
    eq = curve_of(10000, 11000)
    r = build_report(
        [],
        eq,
        D(10000),
        NAMES,
        ("Nifty 200 TRI", {eq[0][0]: D(200)}),
    )
    b = r["benchmark"]
    assert b["curve"] == [] and b["return"] is None and "no value for 1 of 2 days" in b["note"]


def test_no_index_at_all_is_just_absent():
    assert rep([])["benchmark"] is None


def test_cost_drag_is_the_share_of_the_profit_before_charges_that_charges_took():
    r = rep([BUY1, BUY2, SELL])  # net 344, charges 6: 350 before charges
    s = r["summary"]
    assert (s["pre_charge_pnl"], s["cost_drag"]) == ("350", "0.0171")


def test_cost_drag_is_undefined_when_nothing_was_made_before_charges():
    losing = [BUY1, (2, date(2024, 1, 5), 7, "SELL", D(10), D(90), D(2))]
    s = rep(losing)["summary"]
    assert s["pre_charge_pnl"] == "-100" and s["cost_drag"] is None
    assert rep([])["summary"]["cost_drag"] is None


# --- bonus / split: the engine adds shares at the ex-date; the report must pair the sells against them ---
B100 = (1, date(2024, 1, 1), 7, "BUY", D(100), D(100), D(2))
BONUS = (date(2024, 1, 15), 7, D(100))  # 1:1 bonus, 100 extra shares


def test_sell_after_a_bonus_pairs_the_extra_shares_at_the_diluted_cost():
    s = (2, date(2024, 2, 1), 7, "SELL", D(200), D(80), D(3))
    r = build_report([B100, s], [(date(2024, 1, 1), D(1000))], D(1000), NAMES, splits=[BONUS])
    (t,) = r["round_trips"]
    # cost per share is now 50, so 200 shares sold at 80 make 6000 (not -2000 on 100 shares), charges 2 + 3
    assert (t["qty"], t["entry_price"], t["gross"], t["charges"], t["net"]) == (
        "200",
        "50",
        "6000",
        "5",
        "5995",
    )
    assert r["open_positions"] == []


def test_partial_sell_after_a_bonus_leaves_the_rest_open_at_the_diluted_cost():
    s = (2, date(2024, 2, 1), 7, "SELL", D(50), D(80), D(0))
    r = build_report([B100, s], [(date(2024, 1, 1), D(1000))], D(1000), NAMES, splits=[BONUS])
    assert r["round_trips"][0]["gross"] == "1500"  # 50 x (80 - 50)
    assert (r["open_positions"][0]["qty"], r["open_positions"][0]["entry_price"]) == ("150", "50")


def test_a_split_on_the_sell_day_applies_before_that_days_sell():
    s = (2, date(2024, 1, 15), 7, "SELL", D(200), D(80), D(0))
    r = build_report([B100, s], [(date(2024, 1, 1), D(1000))], D(1000), NAMES, splits=[BONUS])
    assert r["round_trips"][0]["qty"] == "200"


def test_a_split_for_a_stock_not_held_or_after_the_last_sale_changes_nothing():
    other = (date(2024, 1, 15), 8, D(100))
    sell_all = (2, date(2024, 1, 10), 7, "SELL", D(100), D(120), D(0))
    late = (date(2024, 3, 1), 7, D(100))
    r = build_report(
        [B100, sell_all], [(date(2024, 1, 1), D(1000))], D(1000), NAMES, splits=[other, late]
    )
    assert (r["round_trips"][0]["qty"], r["round_trips"][0]["gross"]) == ("100", "2000")
    assert r["open_positions"] == []


# --- the headline carries what the whole run paid and received, so the page can add up ---
def test_headline_charges_default_to_every_fills_charges_open_buys_included():
    r = rep([BUY1, BUY2, SELL])  # 2 + 2 + 3; the closed trades only carry 4 + 2 = 6 of it
    assert r["headline"]["charges"] == "7"
    assert r["summary"]["charges"] == "6"
    assert r["headline"]["dividends"] == "0"


def test_headline_uses_the_runs_own_fee_total_when_it_has_charges_outside_trades():
    # the engine posts a per-contract-note brokerage minimum that belongs to no single trade
    r = build_report(
        [BUY1, BUY2, SELL],
        [(date(2024, 1, 1), D(10000)), (date(2024, 3, 1), D(10500))],
        D(10000),
        NAMES,
        total_charges=D("7.5"),
        dividends=D(40),
    )
    assert (r["headline"]["charges"], r["headline"]["dividends"]) == ("7.5", "40")

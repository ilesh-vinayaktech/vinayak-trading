from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from algo.ledger.ledger import (
    TOL,
    Conversion,
    ConversionError,
    DuplicateBooking,
    InsufficientCash,
    InsufficientPosition,
    Ledger,
)

DAY = date(2025, 6, 2)
A, B = 1, 2


def ledger(cash=10000):
    return Ledger(D(cash), DAY)


# ---- hand-computed -------------------------------------------------------------------------
def test_buy_then_partial_sell_with_fees_hand_computed():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(1), "trade:1")  # cost 1000, fee 1
    assert lg.cash == D(8999) and lg.qty(A) == 10 and lg.cost_basis(A) == D(1000)
    assert lg.equity({A: D(110)}) == D(8999) + D(1100)
    lg.sell(DAY, A, D(4), D(120), D("1.2"), "trade:2")  # proceeds 480, cost removed 400
    assert lg.cash == D("9477.8") and lg.qty(A) == 6 and lg.cost_basis(A) == D(600)
    p = lg.pnl({A: D(130)})
    assert (p.realized, p.unrealized, p.dividends, p.fees) == (D(80), D(180), D(0), D("2.2"))
    assert p.net == D("257.8") == lg.equity({A: D(130)}) - D(10000)  # the identity
    assert lg.reconcile({A: D(130)}) == []


def test_average_cost_across_two_buys():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg.buy(DAY, A, D(10), D(120), D(0), "trade:2")  # cost 2200 for 20 => avg 110
    lg.sell(DAY, A, D(5), D(130), D(0), "trade:3")  # removes 550, realizes 650 - 550 = 100
    assert lg.pnl({A: D(130)}).realized == D(100) and lg.cost_basis(A) == D(1650)


def test_a_full_exit_clears_the_cost_basis_exactly_even_with_awkward_averages():
    lg = ledger(100000)
    lg.buy(DAY, A, D(3), D("33.33"), D(0), "trade:1")
    lg.buy(DAY, A, D(7), D("41.17"), D(0), "trade:2")
    lg.sell(DAY, A, D(4), D("50"), D(0), "trade:3")
    lg.sell(DAY, A, D(6), D("50"), D(0), "trade:4")
    assert lg.qty(A) == 0 and lg.cost_basis(A) == 0 and lg.quantities() == {}
    assert lg.reconcile({}) == []


def test_bonus_or_split_changes_shares_not_cost():
    lg = ledger()
    lg.buy(DAY, A, D(100), D(100), D(0), "trade:1")
    lg.apply_split(DAY, A, D(2), D(1), "action:1")  # 1:1 bonus
    assert lg.qty(A) == 200 and lg.cost_basis(A) == D(10000)
    lg.sell(DAY, A, D(50), D(60), D(0), "trade:2")  # avg cost is now 50
    assert lg.pnl({A: D(60)}).realized == D(500)
    assert lg.equity({A: D(50)}) == lg.cash + 150 * D(50)
    lg2 = ledger()
    lg2.buy(DAY, A, D(3), D(100), D(0), "trade:1")
    lg2.apply_split(DAY, A, D(5), D(3), "action:1")  # fractional result is kept exactly
    assert lg2.qty(A) == D(5)


def test_dividends_credit_cash_on_the_shares_held_and_count_in_pnl():
    lg = ledger()
    lg.buy(DAY, A, D(100), D(100), D(0), "trade:1")
    assert lg.credit_dividend(DAY, A, D(2), "action:1") == D(200)
    assert lg.cash == D(200) and lg.pnl({A: D(100)}).dividends == D(200)
    assert lg.pnl({A: D(100)}).net == D(200) == lg.equity({A: D(100)}) - D(10000)


def test_fees_are_kept_apart_from_the_price_result():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(5), "trade:1")
    lg.sell(DAY, A, D(10), D(100), D(5), "trade:2")  # flat price
    p = lg.pnl({})
    assert p.realized == 0 and p.fees == D(10) and p.net == D(-10)
    assert lg.cash == D(9990)


def test_unmodelled_actions_are_flagged_and_listed():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg.flag_unmodelled(DAY, A, "resolved", "action:9")
    (e,) = lg.unmodelled()
    assert (e.kind, e.instrument_id, e.qty, e.amount) == ("UNMODELLED:resolved", A, D(10), 0)
    assert lg.reconcile({A: D(100)}) == []  # flagged, but the arithmetic still agrees


# ---- refusals ------------------------------------------------------------------------------
def test_a_source_event_can_be_booked_only_once():
    lg = ledger()
    lg.buy(DAY, A, D(1), D(100), D(0), "trade:1")
    for call in (
        lambda: lg.buy(DAY, A, D(1), D(100), D(0), "trade:1"),
        lambda: lg.sell(DAY, A, D(1), D(100), D(0), "trade:1"),
        lambda: lg.apply_split(DAY, A, D(2), D(1), "trade:1"),
        lambda: lg.credit_dividend(DAY, A, D(1), "trade:1"),
        lambda: lg.flag_unmodelled(DAY, A, "x", "trade:1"),
        lambda: lg.buy(DAY, A, D(1), D(100), D(0), "initial"),
    ):
        with pytest.raises(DuplicateBooking):
            call()
    assert lg.qty(A) == 1 and len(lg.entries) == 3  # nothing was half-posted


def test_cash_and_position_limits():
    lg = ledger(1000)
    with pytest.raises(InsufficientCash):
        lg.buy(DAY, A, D(10), D(100), D(1), "trade:1")  # 1001 > 1000
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:2")  # exactly 1000 is fine
    with pytest.raises(InsufficientPosition):
        lg.sell(DAY, A, D(11), D(100), D(0), "trade:3")
    with pytest.raises(InsufficientPosition):
        lg.sell(DAY, B, D(1), D(100), D(0), "trade:4")
    assert lg.reconcile({A: D(100)}) == []


@pytest.mark.parametrize(
    "call",
    [
        lambda lg: lg.buy(DAY, A, D(0), D(100), D(0), "t"),
        lambda lg: lg.buy(DAY, A, D(1), D(0), D(0), "t"),
        lambda lg: lg.buy(DAY, A, D(1), D(100), D(-1), "t"),
        lambda lg: lg.sell(DAY, A, D(0), D(100), D(0), "t"),
        lambda lg: lg.sell(DAY, A, D(1), D(-1), D(0), "t"),
        lambda lg: lg.sell(DAY, A, D(1), D(100), D(-1), "t"),
        lambda lg: lg.apply_split(DAY, A, D(0), D(1), "t"),
        lambda lg: lg.apply_split(DAY, A, D(1), D(-1), "t"),
        lambda lg: lg.apply_split(DAY, A, D(2), D(1), "t"),  # nothing held
        lambda lg: lg.credit_dividend(DAY, A, D(0), "t"),
        lambda lg: lg.credit_dividend(DAY, A, D(1), "t"),  # nothing held
    ],
)
def test_nonsense_input_is_rejected_without_booking_anything(call):
    lg = ledger()
    lg.buy(DAY, B, D(1), D(10), D(0), "trade:0")
    before = len(lg.entries)
    with pytest.raises(ValueError):
        call(lg)
    assert len(lg.entries) == before and "t" not in lg._booked


def test_negative_initial_cash_is_rejected_and_missing_prices_are_loud():
    with pytest.raises(ValueError):
        Ledger(D(-1), DAY)
    lg = ledger()
    lg.buy(DAY, A, D(1), D(10), D(0), "trade:1")
    for f in (lg.equity, lg.unrealized, lg.pnl, lg.reconcile):
        with pytest.raises(LookupError, match="no price for held instrument 1"):
            f({B: D(1)})
    assert ledger().reconcile({}) == []  # nothing held: no prices needed


# ---- reconcile() really detects corruption -------------------------------------------------
def traded():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(2), "trade:1")
    lg.sell(DAY, A, D(4), D(120), D(1), "trade:2")
    lg.credit_dividend(DAY, A, D(1), "action:1")
    return lg, {A: D(110)}


def test_a_clean_ledger_reconciles():
    lg, prices = traded()
    assert lg.reconcile(prices) == [] and lg.reconcile() == []


def has(problems, text):
    return any(text in p for p in problems)


def test_running_cash_that_drifts_from_the_entries_is_detected():
    lg, prices = traded()
    lg._cash += D("0.01")
    assert has(lg.reconcile(prices), "cash: running")


def test_running_positions_and_cost_that_drift_are_detected():
    lg, prices = traded()
    lg._qty[A] += D(1)
    lg._cost[A] += D(5)
    p = lg.reconcile()
    assert has(p, f"position {A}: running") and has(p, f"cost basis {A}: running")


def test_running_pnl_totals_that_drift_are_detected():
    lg, _ = traded()
    lg._realized += 1
    lg._dividends += 1
    lg._fees += 1
    p = lg.reconcile()
    assert has(p, "realized: running") and has(p, "dividends: running") and has(p, "fees: running")


def test_a_forged_cash_entry_breaks_the_trade_cross_checks_and_the_identity():
    lg, prices = traded()
    lg.entries[1] = replace(lg.entries[1], amount=lg.entries[1].amount + D(5))  # BUY position cost
    p = lg.reconcile(prices)
    assert has(p, "trade:1: BUY cash") and has(p, "cost basis") and has(p, "identity broken")


def test_a_trade_missing_one_of_its_entries_is_detected():
    lg, _ = traded()
    del lg.entries[1]  # the BUY position entry
    p = lg.reconcile()
    assert has(p, "trade:1: BUY needs both") and has(p, "entry numbering")


def test_sell_without_its_realized_pnl_entry_is_detected():
    lg, _ = traded()
    lg.entries = [e for e in lg.entries if not (e.ledger == "pnl" and e.ref == "trade:2")]
    assert has(lg.reconcile(), "trade:2: SELL needs position, cash and realized-P&L entries")


def test_wrong_realized_pnl_is_detected():
    lg, _ = traded()
    i = next(n for n, e in enumerate(lg.entries) if e.ledger == "pnl")
    lg.entries[i] = replace(lg.entries[i], amount=lg.entries[i].amount + D(1))
    assert has(lg.reconcile(), "realized 41 != proceeds - cost removed") or has(
        lg.reconcile(), "trade:2: realized"
    )


def test_fee_entries_must_match_the_cash_paid():
    lg, _ = traded()
    i = next(n for n, e in enumerate(lg.entries) if e.ledger == "fee")
    lg.entries[i] = replace(lg.entries[i], amount=lg.entries[i].amount + D(1))
    assert has(lg.reconcile(), "trade:1: fee")
    lg2, _ = traded()
    lg2.entries = [
        e
        for e in lg2.entries
        if not (e.ledger == "cash" and e.kind == "FEE" and e.ref == "trade:2")
    ]
    assert has(lg2.reconcile(), "trade:2: a fee needs both")


def test_duplicated_and_renumbered_entries_are_detected():
    lg, _ = traded()
    lg.entries.append(replace(lg.entries[-1], seq=len(lg.entries) + 1))
    assert has(lg.reconcile(), "duplicate booking of cash/DIVIDEND for action:1")
    lg2, _ = traded()
    lg2.entries[3] = replace(lg2.entries[3], seq=99)
    assert has(lg2.reconcile(), "entry numbering: position 4 has seq 99")


def test_a_negative_or_orphan_cost_position_is_detected():
    lg, _ = traded()
    lg.entries.append(
        replace(lg.entries[1], seq=len(lg.entries) + 1, ref="trade:9", qty=D(-50), kind="SELL")
    )
    assert has(lg.reconcile(), f"position {A} is negative")
    lg2 = ledger()
    lg2.buy(DAY, A, D(1), D(10), D(0), "trade:1")
    lg2.entries.append(
        replace(
            lg2.entries[1],
            seq=len(lg2.entries) + 1,
            ref="trade:2",
            kind="SELL",
            qty=D(-1),
            amount=D(0),
        )
    )
    assert has(lg2.reconcile(), f"cost basis {A} remains")


# ---- property: any sequence of valid operations leaves the books in agreement ---------------
op = st.one_of(
    st.tuples(
        st.just("buy"),
        st.integers(1, 3),
        st.integers(1, 50),
        st.integers(1, 500),
        st.integers(0, 20),
    ),
    st.tuples(
        st.just("sell"),
        st.integers(1, 3),
        st.integers(1, 50),
        st.integers(1, 500),
        st.integers(0, 20),
    ),
    st.tuples(
        st.just("split"), st.integers(1, 3), st.integers(1, 5), st.integers(1, 5), st.just(0)
    ),
    st.tuples(st.just("div"), st.integers(1, 3), st.integers(1, 20), st.just(1), st.just(0)),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(op, max_size=40), st.lists(st.integers(1, 800), min_size=3, max_size=3))
def test_random_valid_sequences_always_reconcile_and_obey_the_identities(ops, marks):
    lg = ledger(50000)
    for n, (kind, iid, a, b, fee) in enumerate(ops):
        ref = f"op:{n}"
        try:
            if kind == "buy":
                lg.buy(DAY, iid, D(a), D(b), D(fee), ref)
            elif kind == "sell":
                lg.sell(DAY, iid, D(a), D(b), D(fee), ref)
            elif kind == "split":
                lg.apply_split(DAY, iid, D(a), D(b), ref)
            else:
                lg.credit_dividend(DAY, iid, D(a), ref)
        except (InsufficientCash, InsufficientPosition, ValueError):
            continue  # a refused operation must leave no trace (checked below)
    prices = {i: D(m) for i, m in zip((1, 2, 3), marks, strict=True)}
    assert lg.reconcile(prices) == []
    pnl = lg.pnl(prices)
    assert abs(pnl.net - (lg.equity(prices) - D(50000))) <= TOL  # average cost divides: 28 digits
    cash_entries = sum(
        (e.amount for e in lg.entries if e.ledger == "cash" and e.kind != "INITIAL"), D(0)
    )
    assert abs(lg.cash - (D(50000) + cash_entries)) <= TOL  # 28-digit sums differ by order
    for iid, q in lg.quantities().items():
        held = sum(
            (e.qty for e in lg.entries if e.ledger == "position" and e.instrument_id == iid), D(0)
        )
        assert abs(q - held) <= TOL and q > 0
    assert lg.cash >= 0
    assert [e.seq for e in lg.entries] == list(range(1, len(lg.entries) + 1))


def test_the_stated_initial_cash_must_match_the_initial_entry():
    lg = ledger()
    lg.initial_cash = D(9999)
    assert has(lg.reconcile(), "initial cash: stated 9999 != entries 10000")


def test_the_identity_is_computed_from_the_entries_so_a_forged_cost_entry_cannot_hide():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg._cost[A] += D(5)  # running state forged to agree with the forged entry
    lg.entries[1] = replace(lg.entries[1], amount=lg.entries[1].amount + D(5))
    p = lg.reconcile({A: D(100)})
    assert has(p, "identity broken") and has(p, "trade:1: BUY cash")


# ---- gaps found by mutation testing -------------------------------------------------------------
from algo.ledger.ledger import Entry  # noqa: E402

D2, D3, D4, D5, D6 = (date(2025, 6, n) for n in (3, 4, 5, 6, 9))


def test_every_posting_writes_exactly_these_entries():
    lg = ledger()
    lg.buy(D2, A, D(10), D(100), D(1), "trade:1")
    lg.sell(D3, A, D(4), D(120), D("1.5"), "trade:2")
    lg.apply_split(D4, A, D(2), D(1), "action:1")
    lg.credit_dividend(D5, A, D(2), "action:2")
    lg.flag_unmodelled(D6, A, "demerger", "action:3")
    assert lg.entries == [
        Entry(1, DAY, "cash", "INITIAL", None, D(0), D(10000), "initial"),
        Entry(2, D2, "position", "BUY", A, D(10), D(1000), "trade:1"),
        Entry(3, D2, "cash", "BUY", A, D(0), D(-1000), "trade:1"),
        Entry(4, D2, "fee", "COMMISSION", A, D(0), D(1), "trade:1"),
        Entry(5, D2, "cash", "FEE", A, D(0), D(-1), "trade:1"),
        Entry(6, D3, "position", "SELL", A, D(-4), D(-400), "trade:2"),
        Entry(7, D3, "cash", "SELL", A, D(0), D(480), "trade:2"),
        Entry(8, D3, "pnl", "REALIZED", A, D(0), D(80), "trade:2"),
        Entry(9, D3, "fee", "COMMISSION", A, D(0), D("1.5"), "trade:2"),
        Entry(10, D3, "cash", "FEE", A, D(0), D("-1.5"), "trade:2"),
        Entry(11, D4, "position", "SPLIT", A, D(6), D(0), "action:1"),  # 6 held -> 12
        Entry(12, D5, "cash", "DIVIDEND", A, D(12), D(24), "action:2"),
        Entry(13, D6, "event", "UNMODELLED:demerger", A, D(12), D(0), "action:3"),
    ]
    assert lg.reconcile({A: D(100)}) == []


def test_boundaries_of_the_input_checks():
    assert ledger(0).cash == 0 and Ledger(D("0.5"), DAY).cash == D(
        "0.5"
    )  # zero / tiny cash is fine
    lg = ledger()
    lg.buy(DAY, A, D(2), D("0.5"), D(0), "trade:1")  # a sub-rupee price is a valid price
    lg.buy(DAY, B, D(2), D(1), D(0), "trade:2")
    lg.sell(DAY, A, D(1), D("0.5"), D(0), "trade:3")
    lg.sell(DAY, B, D(1), D(1), D(0), "trade:4")
    with pytest.raises(ValueError, match="^sell needs qty > 0, price > 0, fee >= 0$"):
        lg.sell(DAY, A, D(1), D(0), D(0), "trade:5")  # a zero price is not
    with pytest.raises(ValueError, match="^buy needs qty > 0, price > 0, fee >= 0$"):
        lg.buy(DAY, A, D(1), D(0), D(0), "trade:6")


def test_cash_check_allows_the_tolerance_edge_and_reports_the_amounts():
    lg = ledger(1000)
    lg.buy(DAY, A, D(10), D(100), TOL, "trade:1")  # needs exactly cash + TOL: allowed
    lg2 = ledger(1000)
    with pytest.raises(InsufficientCash, match="^need 1001, have 1000$"):
        lg2.buy(DAY, A, D(10), D(100), D(1), "trade:1")


def test_a_full_exit_clears_the_basis_exactly_even_after_an_inexact_partial_sale():
    lg = ledger()
    lg.buy(DAY, A, D(1), D("33.33"), D(0), "trade:1")
    lg.buy(DAY, A, D(2), D("33.335"), D(0), "trade:2")  # 3 shares, cost 100.00
    lg.sell(DAY, A, D(1), D(40), D(0), "trade:3")  # average 33.333..., removes an inexact amount
    lg.sell(DAY, A, D(2), D(40), D(0), "trade:4")
    assert lg.qty(A) == 0 and lg.cost_basis(A) == 0  # exactly zero, not a 1e-26 residue


@pytest.mark.parametrize("num,den", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_split_ratio_must_be_positive_on_both_sides(num, den):
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    with pytest.raises(ValueError, match="^split ratio must be positive$"):
        lg.apply_split(DAY, A, D(num), D(den), "action:1")
    assert lg.qty(A) == 10


def test_a_reverse_split_ratio_below_one_is_valid_and_zero_dividend_is_not():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg.apply_split(DAY, A, D(1), D(2), "action:1")  # consolidation: 10 shares -> 5
    assert lg.qty(A) == 5 and lg.cost_basis(A) == D(1000)
    with pytest.raises(ValueError, match="^dividend per share must be positive$"):
        lg.credit_dividend(DAY, A, D(0), "action:2")
    with pytest.raises(ValueError, match="^nothing held to receive a dividend$"):
        lg.credit_dividend(DAY, B, D(1), "action:3")
    with pytest.raises(ValueError, match="^nothing held to adjust$"):
        lg.apply_split(DAY, B, D(2), D(1), "action:4")


def test_state_present_in_only_one_of_the_two_books_is_detected():
    lg = ledger()
    lg.buy(DAY, A, D(1), D(10), D(0), "trade:1")
    lg._qty[99] += D(1)  # running state mentions an instrument no entry does
    lg._cost[99] += D(7)
    p = lg.reconcile()
    assert has(p, "position 99: running 1 != entries 0") and has(
        p, "cost basis 99: running 7 != entries 0"
    )
    lg2 = ledger()
    lg2.entries.append(
        Entry(2, DAY, "position", "BUY", 98, D(2), D(20), "trade:50")
    )  # entries only
    p2 = lg2.reconcile()
    assert has(p2, "position 98: running 0 != entries 2") and has(
        p2, "cost basis 98: running 0 != entries 20"
    )


@pytest.mark.parametrize("attr", ["_cash", "_realized", "_dividends", "_fees"])
def test_running_totals_exactly_at_the_tolerance_pass_and_beyond_it_fail(attr):
    lg, _ = traded()
    setattr(lg, attr, getattr(lg, attr) + TOL)
    assert lg.reconcile() == []
    setattr(lg, attr, getattr(lg, attr) + 2 * TOL)
    assert lg.reconcile() != []


def test_position_and_cost_and_initial_cash_exactly_at_the_tolerance():
    lg, _ = traded()
    lg._qty[A] += TOL
    lg._cost[A] += TOL
    lg.initial_cash += TOL
    assert lg.reconcile() == []
    lg._qty[A] += 2 * TOL
    lg._cost[A] += 2 * TOL
    lg.initial_cash += 2 * TOL
    p = lg.reconcile()
    assert has(p, f"position {A}") and has(p, f"cost basis {A}") and has(p, "initial cash")


@pytest.mark.parametrize(
    "index", [2, 7, 9], ids=["buy cash", "realized pnl", "fee"]
)  # entries of trade:1 BUY cash / trade:2 REALIZED / trade:1 COMMISSION
def test_trade_cross_checks_tolerate_exactly_tol_and_flag_more(index):
    lg, _ = traded()
    e = lg.entries[index]
    lg.entries[index] = replace(e, amount=e.amount + TOL)
    # the same forgery must not trip any check that is allowed TOL of slack
    lg._cash += TOL if e.ledger == "cash" else 0
    lg._realized += TOL if e.ledger == "pnl" else 0
    lg._fees += TOL if e.ledger == "fee" else 0
    assert lg.reconcile() == []
    lg.entries[index] = replace(e, amount=e.amount + 3 * TOL)
    assert lg.reconcile() != []


def test_a_position_at_exactly_minus_tol_is_not_negative_but_orphan_cost_is_still_caught():
    lg = ledger()
    lg.buy(DAY, A, D(1), D(10), D(0), "trade:1")
    lg.entries.append(
        Entry(len(lg.entries) + 1, DAY, "position", "SELL", A, -(D(1) + TOL), D(-9), "trade:9")
    )
    p = lg.reconcile()
    assert not has(p, "is negative") and has(p, f"cost basis {A} remains (1) with no shares")


def test_the_entry_only_identity_catches_a_forged_cost_without_any_prices():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg.entries[1] = replace(lg.entries[1], amount=lg.entries[1].amount + D(5))
    assert has(lg.reconcile(), "identity broken: cash movements, cost basis and P&L disagree by 5")


def test_the_valuation_check_catches_a_running_state_that_valuations_would_misreport():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg._cost[A] += D(1)  # running basis wrong: net P&L would be misreported
    p = lg.reconcile({A: D(120)})
    assert has(p, "valuation: equity - initial != net P&L by 1")


def test_fee_message_names_the_amounts_exactly():
    lg, _ = traded()
    i = next(n for n, e in enumerate(lg.entries) if e.ledger == "fee")
    lg.entries[i] = replace(lg.entries[i], amount=lg.entries[i].amount + D(1))
    assert "trade:1: fee 3 != cash paid 2" in lg.reconcile()


def test_cost_basis_of_an_instrument_never_held_is_zero():
    assert ledger().cost_basis(999) == 0 and ledger().qty(999) == 0


def test_orphan_cost_exactly_at_the_tolerance_is_not_reported_but_just_above_it_is():
    lg = ledger()
    lg.buy(DAY, A, D(1), D(10), D(0), "trade:1")
    # an exit that leaves cost of exactly TOL behind (and no shares)
    lg.entries.append(
        Entry(len(lg.entries) + 1, DAY, "position", "SELL", A, D(-1), -(D(10) - TOL), "trade:9")
    )
    assert not has(lg.reconcile(), "remains")
    lg.entries[-1] = replace(lg.entries[-1], amount=-(D(10) - 3 * TOL))
    assert has(lg.reconcile(), f"cost basis {A} remains")


def test_valuation_gap_exactly_at_the_tolerance_passes_and_beyond_it_is_reported():
    lg = ledger()
    lg.buy(DAY, A, D(10), D(100), D(0), "trade:1")
    lg._cost[A] += TOL
    assert not has(lg.reconcile({A: D(120)}), "valuation")
    lg._cost[A] += 2 * TOL
    assert has(lg.reconcile({A: D(120)}), "valuation: equity - initial != net P&L by")


# ---- itemised charges ---------------------------------------------------------------------------
CH = [
    ("STT", D("100")),
    ("EXCHANGE_TRANSACTION", D("3.07")),
    ("STAMP_DUTY", D("15")),
    ("GST", D("0.57")),
]


def test_itemised_charges_each_get_a_fee_entry_and_a_matching_cash_entry():
    lg = ledger(200000)
    lg.buy(D2, A, D(100), D(1000), D(0), "trade:1", charges=CH)
    assert lg.entries[1:] == [
        Entry(2, D2, "position", "BUY", A, D(100), D(100000), "trade:1"),
        Entry(3, D2, "cash", "BUY", A, D(0), D(-100000), "trade:1"),
        Entry(4, D2, "fee", "STT", A, D(0), D(100), "trade:1"),
        Entry(5, D2, "cash", "FEE:STT", A, D(0), D(-100), "trade:1"),
        Entry(6, D2, "fee", "EXCHANGE_TRANSACTION", A, D(0), D("3.07"), "trade:1"),
        Entry(7, D2, "cash", "FEE:EXCHANGE_TRANSACTION", A, D(0), D("-3.07"), "trade:1"),
        Entry(8, D2, "fee", "STAMP_DUTY", A, D(0), D(15), "trade:1"),
        Entry(9, D2, "cash", "FEE:STAMP_DUTY", A, D(0), D(-15), "trade:1"),
        Entry(10, D2, "fee", "GST", A, D(0), D("0.57"), "trade:1"),
        Entry(11, D2, "cash", "FEE:GST", A, D(0), D("-0.57"), "trade:1"),
    ]
    assert lg.cash == D(200000) - D(100000) - D("118.64")  # 100 + 3.07 + 15 + 0.57 of charges
    assert lg.reconcile({A: D(1000)}) == []


def test_the_fee_breakdown_and_totals_agree():
    lg = ledger(200000)
    lg.buy(D2, A, D(100), D(1000), D("2"), "trade:1", charges=CH + [("DP_CHARGE", D(0))])
    lg.sell(
        D3,
        A,
        D(100),
        D(1100),
        D(0),
        "trade:2",
        charges=[("STT", D(110)), ("DP_CHARGE", D("15.34"))],
    )
    assert lg.fee_breakdown() == {
        "COMMISSION": D(2),
        "DP_CHARGE": D("15.34"),  # the zero-amount DP line on the buy was skipped
        "EXCHANGE_TRANSACTION": D("3.07"),
        "GST": D("0.57"),
        "STAMP_DUTY": D(15),
        "STT": D(210),
    }
    assert lg.pnl({}).fees == sum(lg.fee_breakdown().values(), D(0)) == D("245.98")
    assert lg.cash == D(200000) - 100000 + 110000 - D("245.98")
    assert lg.pnl({}).realized == D(10000) and lg.reconcile({}) == []


def test_charges_count_toward_the_cash_check_and_the_message_names_the_total():
    lg = ledger(1000)
    with pytest.raises(InsufficientCash, match="^need 1019.5, have 1000$"):
        lg.buy(DAY, A, D(10), D(100), D("0.5"), "trade:1", charges=[("STT", D(19))])
    assert len(lg.entries) == 1  # nothing posted
    lg.buy(DAY, A, D(10), D(90), D(0), "trade:2", charges=[("STT", D(100))])  # exactly 1000: fine
    assert lg.cash == 0


@pytest.mark.parametrize(
    "charges",
    [[("STT", D(1)), ("STT", D(2))], [("COMMISSION", D(1))], [("STT", D(-1))]],
    ids=["duplicate type", "COMMISSION reserved", "negative"],
)
def test_bad_charge_lists_are_rejected_before_anything_is_posted(charges):
    lg = ledger()
    lg.buy(DAY, B, D(1), D(10), D(0), "trade:0")
    before = len(lg.entries)
    for call in (
        lambda: lg.buy(DAY, A, D(1), D(10), D(0), "trade:1", charges=charges),
        lambda: lg.sell(DAY, B, D(1), D(10), D(0), "trade:2", charges=charges),
    ):
        with pytest.raises(
            ValueError,
            match="^charge types must be distinct and not COMMISSION$|^charges cannot be negative$",
        ):
            call()
    assert len(lg.entries) == before and lg.qty(B) == 1


def traded_with_charges():
    lg = ledger(200000)
    lg.buy(D2, A, D(100), D(1000), D(0), "trade:1", charges=CH)
    return lg


def test_a_forged_itemised_fee_is_detected_with_its_type_in_the_message():
    lg = traded_with_charges()
    i = next(n for n, e in enumerate(lg.entries) if e.ledger == "fee" and e.kind == "STT")
    lg.entries[i] = replace(lg.entries[i], amount=lg.entries[i].amount + D(5))
    p = lg.reconcile()
    assert "trade:1: STT fee 105 != cash paid 100" in p and has(
        p, "fees[STT]: running 100 != entries 105"
    )


def test_a_missing_counterpart_of_an_itemised_fee_is_detected():
    lg = traded_with_charges()
    lg.entries = [e for e in lg.entries if not (e.ledger == "cash" and e.kind == "FEE:STAMP_DUTY")]
    assert "trade:1: a STAMP_DUTY fee needs both a fee and a cash entry" in lg.reconcile()
    lg2 = traded_with_charges()
    lg2.entries = [e for e in lg2.entries if not (e.ledger == "fee" and e.kind == "GST")]
    assert "trade:1: a GST fee needs both a fee and a cash entry" in lg2.reconcile()


def test_per_type_running_totals_that_drift_are_detected_and_exact_tolerance_passes():
    lg = traded_with_charges()
    lg._fees_by["STT"] += TOL
    assert lg.reconcile() == []
    lg._fees_by["STT"] += 2 * TOL
    assert has(lg.reconcile(), "fees[STT]: running")
    lg2 = traded_with_charges()
    lg2._fees_by["INVENTED"] = D(7)  # a type with running money but no entries
    assert has(lg2.reconcile(), "fees[INVENTED]: running 7 != entries 0")


# ---- note-level charges (not tied to one trade) ------------------------------------------------
def test_post_charges_books_itemised_fees_without_a_trade():
    lg = ledger()
    lg.post_charges(D2, [("BROKERAGE", D("0.01")), ("GST", D(0)), ("STT", D("2"))], "note:1")
    assert lg.entries[1:] == [
        Entry(2, D2, "fee", "BROKERAGE", None, D(0), D("0.01"), "note:1"),
        Entry(3, D2, "cash", "FEE:BROKERAGE", None, D(0), D("-0.01"), "note:1"),
        Entry(4, D2, "fee", "STT", None, D(0), D(2), "note:1"),  # the zero GST line is skipped
        Entry(5, D2, "cash", "FEE:STT", None, D(0), D(-2), "note:1"),
    ]
    assert lg.cash == D("9997.99") and lg.fee_breakdown() == {"BROKERAGE": D("0.01"), "STT": D(2)}
    assert lg.reconcile({}) == []


def test_post_charges_refuses_nothing_to_charge_more_than_the_cash_and_a_repeat():
    lg = ledger(5)
    with pytest.raises(ValueError, match="^nothing to charge$"):
        lg.post_charges(DAY, [("STT", D(0))], "note:1")
    with pytest.raises(InsufficientCash, match="^need 5.01, have 5$"):
        lg.post_charges(DAY, [("STT", D("5.01"))], "note:1")
    with pytest.raises(ValueError, match="^charge types must be distinct and not COMMISSION$"):
        lg.post_charges(DAY, [("STT", D(1)), ("STT", D(1))], "note:1")
    assert len(lg.entries) == 1  # nothing was booked by the refusals
    lg.post_charges(DAY, [("STT", D(5))], "note:1")  # exactly the cash: fine
    assert lg.cash == 0
    lg2 = ledger(10)
    lg2.post_charges(DAY, [("STT", D(5))], "note:1")
    with pytest.raises(DuplicateBooking):
        lg2.post_charges(DAY, [("STT", D(1))], "note:1")


# ---- more gaps found by mutation testing ---------------------------------------------------------
def test_zero_amount_charges_leave_no_entries_at_all():
    lg = ledger(200000)
    lg.buy(D2, A, D(100), D(1000), D(0), "trade:1", charges=[("STT", D(100)), ("GST", D(0))])
    assert all(e.amount != 0 for e in lg.entries if e.ledger == "fee")
    assert [e.kind for e in lg.entries if e.ledger == "fee"] == ["STT"]
    assert lg.fee_breakdown() == {"STT": D(100)}


def test_two_note_level_postings_with_different_refs_are_both_accepted():
    lg = ledger()
    lg.post_charges(D2, [("BROKERAGE", D("0.01"))], "note:1")
    lg.post_charges(D3, [("BROKERAGE", D("0.01"))], "note:2")
    assert lg.fee_breakdown() == {"BROKERAGE": D("0.02")} and lg.reconcile({}) == []


def test_a_cash_fee_entry_with_no_fee_entry_is_detected_for_each_naming_style():
    lg = ledger()
    lg.entries.append(Entry(2, DAY, "cash", "FEE", None, D(0), D(-3), "trade:7"))
    lg.entries.append(Entry(3, DAY, "cash", "FEE:STT", None, D(0), D(-4), "trade:8"))
    p = lg.reconcile()
    assert "trade:7: a fee needs both a fee and a cash entry" in p
    assert "trade:8: a STT fee needs both a fee and a cash entry" in p


# ---- security conversion (ISIN change) --------------------------------------------------------
OLD, NEW, OTHER = 2653, 1589, 7
CHANGE = date(2024, 1, 5)
BEFORE = date(2024, 1, 4)
BUY_DAY = date(2023, 12, 29)  # purchases of the old instrument precede the conversion


def conv(**kw):
    base = dict(source=OLD, target=NEW, effective=CHANGE, num=D(10), den=D(1), ref="convert:2653:1589:2024-01-05",
                verified=True, evidence=("NSE circular CML60084",), last_source_session=BEFORE,
                absorbs=(CHANGE, "split"))  # fmt: skip
    return Conversion(**{**base, **kw})


def held(qty=100, price=250, cash=100000):
    lg = ledger(cash)
    lg.register_conversion(conv())
    lg.buy(BUY_DAY, OLD, D(qty), D(price), D(0), "trade:1")
    return lg


def test_a_conversion_moves_quantity_and_cost_creates_no_pnl_and_keeps_equity():
    lg = held()  # 100 old shares, cost 25,000, average 250
    cash, equity_before = lg.cash, lg.equity({OLD: D(260)})
    assert lg.apply_conversion(CHANGE, OLD) is True
    assert (lg.qty(OLD), lg.cost_basis(OLD)) == (0, 0)
    assert (lg.qty(NEW), lg.cost_basis(NEW)) == (D(1000), D(25000))  # average cost 25
    assert lg.cash == cash and lg.pnl({NEW: D(26)}).realized == 0
    assert lg.equity({NEW: D(26)}) == equity_before  # the same wealth, on the new scale
    assert lg.pnl({NEW: D(26)}).unrealized == D(
        1000
    )  # moves only with the price: 1000 x 26 - 25,000
    out, inn = lg.entries[-2:]
    assert (out.ledger, out.kind, out.instrument_id, out.qty, out.amount) == (
        "position",
        "CONVERT_OUT",
        OLD,
        D(-100),
        D(-25000),
    )
    assert (inn.ledger, inn.kind, inn.instrument_id, inn.qty, inn.amount) == (
        "position",
        "CONVERT_IN",
        NEW,
        D(1000),
        D(25000),
    )
    assert out.ref == inn.ref == "convert:2653:1589:2024-01-05"
    assert out.day == inn.day == CHANGE  # both halves are dated the day the target starts holding
    assert {e.ledger for e in lg.entries[-2:]} == {"position"}  # no cash, fee or pnl entry
    assert lg.reconcile({NEW: D(26)}) == []


def test_several_purchases_carry_their_average_cost_across():
    lg = ledger()
    lg.register_conversion(conv())
    lg.buy(BUY_DAY, OLD, D(10), D(100), D(0), "trade:1")
    lg.buy(BUY_DAY, OLD, D(10), D(120), D(0), "trade:2")  # 20 shares, cost 2,200
    lg.apply_conversion(CHANGE, OLD)
    assert (lg.qty(NEW), lg.cost_basis(NEW)) == (D(200), D(2200))
    lg.sell(
        CHANGE, NEW, D(50), D(13), D(0), "trade:3"
    )  # removes 2,200 x 50/200 = 550, proceeds 650
    assert lg.pnl({NEW: D(13)}).realized == D(100) and lg.reconcile({NEW: D(13)}) == []


def test_a_position_partly_realised_before_and_after_the_conversion():
    lg = held()
    lg.sell(
        BEFORE, OLD, D(40), D(300), D(0), "trade:2"
    )  # removes 10,000, realises 2,000; 60 shares, cost 15,000
    assert lg.pnl({OLD: D(300)}).realized == D(2000)
    lg.apply_conversion(CHANGE, OLD)
    assert (lg.qty(NEW), lg.cost_basis(NEW)) == (D(600), D(15000)) and lg.pnl(
        {NEW: D(30)}
    ).realized == D(2000)  # unchanged
    lg.sell(
        CHANGE, NEW, D(100), D(30), D(0), "trade:3"
    )  # removes 2,500, proceeds 3,000: realises 500
    assert lg.pnl({NEW: D(30)}).realized == D(2500)
    assert lg.reconcile({NEW: D(30)}) == []


def test_other_holdings_are_untouched_and_no_position_means_no_entries():
    lg = ledger()
    lg.register_conversion(conv())
    lg.buy(BUY_DAY, OTHER, D(5), D(100), D(0), "trade:1")
    n = len(lg.entries)
    assert lg.apply_conversion(CHANGE, OLD) is False  # nothing held in the source: nothing booked
    assert len(lg.entries) == n and lg.qty(OTHER) == 5
    lg.buy(BUY_DAY, OLD, D(1), D(250), D(0), "trade:2")
    lg.apply_conversion(CHANGE, OLD)
    assert lg.qty(OTHER) == 5 and lg.cost_basis(OTHER) == D(500) and lg.qty(NEW) == 10


def test_replaying_a_conversion_cannot_apply_it_twice():
    lg = held()
    lg.apply_conversion(CHANGE, OLD)
    n = len(lg.entries)
    assert lg.apply_conversion(CHANGE, OLD) is False and len(lg.entries) == n  # idempotent
    assert lg.qty(NEW) == 1000
    with pytest.raises(DuplicateBooking):
        lg._book("convert:2653:1589:2024-01-05")  # the source event is spent


def test_a_missing_unverified_or_malformed_instruction_is_refused():
    lg = ledger()
    for bad, msg in (
        (conv(verified=False), "unverified"),
        (conv(evidence=()), "evidence"),
        (conv(num=D(0)), "^the conversion ratio must be positive$"),
        (conv(den=D(0)), "^the conversion ratio must be positive$"),
        (conv(den=D(-1)), "^the conversion ratio must be positive$"),
        (conv(target=OLD), "^source and target must be different instruments$"),
        (
            conv(last_source_session=CHANGE),
            "^the last source session must be before the effective date$",
        ),
    ):
        with pytest.raises(ConversionError, match=msg):
            lg.register_conversion(bad)
    with pytest.raises(ConversionError, match="no conversion registered"):
        lg.apply_conversion(CHANGE, OLD)  # nothing registered: never inferred
    lg.register_conversion(conv())
    with pytest.raises(ConversionError, match="already registered"):
        lg.register_conversion(conv(ref="convert:other"))
    with pytest.raises(ConversionError, match="already registered"):
        lg.register_conversion(
            conv(source=OTHER, ref="convert:x")
        )  # the target is already someone's target
    with pytest.raises(ConversionError, match="before its effective date"):
        lg.apply_conversion(BEFORE, OLD)
    held_target = ledger()
    held_target.buy(BUY_DAY, NEW, D(1), D(10), D(0), "trade:9")
    with pytest.raises(ConversionError, match="already holds"):
        held_target.register_conversion(conv())


def test_trading_the_wrong_identity_around_the_effective_date_is_refused():
    lg = ledger()
    lg.register_conversion(conv())
    lg.buy(BEFORE, OLD, D(10), D(250), D(0), "trade:1")  # the source trades up to the day before
    with pytest.raises(ConversionError, match="no longer tradable"):
        lg.buy(CHANGE, OLD, D(1), D(250), D(0), "trade:2")
    with pytest.raises(ConversionError, match="not tradable before"):
        lg.buy(BEFORE, NEW, D(1), D(25), D(0), "trade:3")
    with pytest.raises(ConversionError, match="no longer tradable"):
        lg.sell(CHANGE, OLD, D(1), D(250), D(0), "trade:4")
    with pytest.raises(ConversionError, match="not tradable before"):
        lg.sell(BEFORE, NEW, D(1), D(25), D(0), "trade:5")
    assert lg.qty(OLD) == 10 and lg.qty(NEW) == 0


def test_reconcile_reports_every_way_a_conversion_can_be_wrong():
    def tampered(edit):
        lg = held()
        lg.apply_conversion(CHANGE, OLD)
        edit(lg)
        return lg.reconcile()

    def entry(lg, kind):
        return next(i for i, e in enumerate(lg.entries) if e.kind == kind)

    def drop_in(lg):
        del lg.entries[entry(lg, "CONVERT_IN")]

    def drop_out(lg):
        del lg.entries[entry(lg, "CONVERT_OUT")]

    def cost_lost(lg):
        i = entry(lg, "CONVERT_IN")
        lg.entries[i] = replace(lg.entries[i], amount=D(24000))

    def wrong_sign(lg):
        i = entry(lg, "CONVERT_IN")
        lg.entries[i] = replace(lg.entries[i], qty=D(-1000))

    def wrong_ratio(lg):
        i = entry(lg, "CONVERT_IN")
        lg.entries[i] = replace(lg.entries[i], qty=D(1001))

    def wrong_instrument(lg):
        i = entry(lg, "CONVERT_IN")
        lg.entries[i] = replace(lg.entries[i], instrument_id=OTHER)

    def with_pnl(lg):
        lg._add(CHANGE, "pnl", "REALIZED", NEW, D(0), D(5), "convert:2653:1589:2024-01-05")

    def early(lg):
        i = entry(lg, "CONVERT_OUT")
        lg.entries[i] = replace(lg.entries[i], day=BEFORE)

    def source_trade_after(lg):
        lg._add(CHANGE, "position", "BUY", OLD, D(1), D(250), "trade:99")
        lg._add(CHANGE, "cash", "BUY", OLD, D(0), D(-250), "trade:99")

    def target_trade_before(lg):
        lg._add(BEFORE, "position", "BUY", NEW, D(1), D(25), "trade:98")
        lg._add(BEFORE, "cash", "BUY", NEW, D(0), D(-25), "trade:98")

    expect = [
        (drop_in, "needs both"), (drop_out, "needs both"), (cost_lost, "cost basis moved"),
        (wrong_sign, "wrong sign"), (wrong_ratio, "ratio"), (wrong_instrument, "wrong instrument"),
        (with_pnl, "must not touch cash, fees or P&L"), (early, "before its effective date"),
        (source_trade_after, "source"), (target_trade_before, "target"),
    ]  # fmt: skip
    for edit, text in expect:
        assert any(text in p for p in tampered(edit)), (edit.__name__, text)
    assert tampered(lambda lg: None) == []


def test_the_balances_rebuilt_from_the_entries_alone_equal_the_running_balances():
    lg = held()
    lg.sell(BEFORE, OLD, D(30), D(260), D("1.5"), "trade:2")
    lg.apply_conversion(CHANGE, OLD)
    lg.buy(CHANGE, OTHER, D(3), D(90), D(0), "trade:3")
    qty, cost = {}, {}
    for e in lg.entries:  # the independent rebuild
        if e.ledger == "position":
            qty[e.instrument_id] = qty.get(e.instrument_id, D(0)) + e.qty
            cost[e.instrument_id] = cost.get(e.instrument_id, D(0)) + e.amount
    assert {i: q for i, q in qty.items() if q} == lg.quantities() == {NEW: D(700), OTHER: D(3)}
    assert (
        all(cost[i] == lg.cost_basis(i) for i in cost)
        and lg.reconcile({NEW: D(26), OTHER: D(90)}) == []
    )


@given(
    qty=st.integers(1, 10_000), price=st.integers(1, 50_000),
    num=st.integers(1, 20), den=st.integers(1, 20), keep=st.integers(1, 100),
)  # fmt: skip
@settings(max_examples=60, deadline=None)
def test_property_conversion_preserves_cost_and_wealth_for_any_ratio(qty, price, num, den, keep):
    lg = ledger(10**12)
    lg.register_conversion(conv(num=D(num), den=D(den)))
    lg.buy(BUY_DAY, OLD, D(qty), D(price), D(0), "trade:1")
    sold = D(qty) * keep // 100
    if sold:
        lg.sell(BEFORE, OLD, sold, D(price) + 1, D(0), "trade:2")
    cost_before, held_before, realized = (
        lg.cost_basis(OLD),
        lg.qty(OLD),
        lg.pnl({OLD: D(price)}).realized,
    )
    lg.apply_conversion(CHANGE, OLD)
    assert lg.cost_basis(NEW) == cost_before and lg.qty(NEW) == held_before * num / den
    new_price = D(price) * den / num  # the same value per ratio
    assert abs(lg.equity({NEW: new_price}) - (lg.cash + held_before * D(price))) <= D("1e-6")
    assert lg.pnl({NEW: new_price}).realized == realized and lg.reconcile({NEW: new_price}) == []


def test_conversion_entries_without_a_registered_instruction_are_still_checked_structurally():
    lg = ledger(100000)
    lg.buy(
        BUY_DAY, OLD, D(100), D(250), D(0), "trade:1"
    )  # a ledger that knows no instruction (e.g. rebuilt)
    lg._add(CHANGE, "position", "CONVERT_OUT", OLD, D(-100), D(-25000), "convert:x")
    lg._add(CHANGE, "position", "CONVERT_IN", NEW, D(1000), D(25000), "convert:x")
    assert lg.reconcile({NEW: D(26)}) == []
    lg._add(CHANGE, "position", "CONVERT_IN", NEW, D(5), D(1), "convert:y")  # an orphan half
    assert any("needs both" in p for p in lg.reconcile())


def _converted():
    lg = held()
    lg.apply_conversion(CHANGE, OLD)
    return lg


def _edit(lg, kind, **kw):
    i = next(i for i, e in enumerate(lg.entries) if e.kind == kind)
    lg.entries[i] = replace(lg.entries[i], **kw)


def test_reconcile_flags_a_zero_or_wrongly_signed_conversion_quantity_at_the_boundary():
    for kind, qty in (("CONVERT_OUT", D(0)), ("CONVERT_OUT", D("0.5")), ("CONVERT_IN", D(0))):
        lg = _converted()
        _edit(lg, kind, qty=qty)
        assert any("wrong sign" in p for p in lg.reconcile()), (kind, qty)


def test_reconcile_reports_the_cost_that_moved_and_the_cost_received_with_their_signs():
    lg = _converted()
    _edit(lg, "CONVERT_IN", amount=D(24000))
    (msg,) = [p for p in lg.reconcile() if "cost basis moved" in p]
    assert msg.endswith(
        "cost basis moved 25000 != received 24000"
    )  # the cost taken out, shown positive
    lg = _converted()
    _edit(lg, "CONVERT_IN", qty=D(1001))
    (msg,) = [p for p in lg.reconcile() if "ratio disagrees" in p]
    assert msg.endswith("(1001 for 100)")  # received for taken out, both positive


def test_a_cash_or_fee_entry_on_a_conversion_is_refused_not_only_a_pnl_one():
    for ledger_name, kind in (("cash", "BUY"), ("fee", "COMMISSION"), ("pnl", "REALIZED")):
        lg = _converted()
        lg._add(CHANGE, ledger_name, kind, NEW, D(0), D(1), "convert:2653:1589:2024-01-05")
        assert any("must not touch cash, fees or P&L" in p for p in lg.reconcile()), ledger_name


def test_the_tolerances_are_inclusive_and_scale_with_the_ratio_denominator():
    # exactly at the tolerance: not a problem (a difference of 1e-9 rupees is average-cost residue)
    lg = _converted()
    _edit(lg, "CONVERT_IN", amount=D(25000) + TOL)
    assert not any("cost basis moved" in p for p in lg.reconcile())
    lg = _converted()
    _edit(lg, "CONVERT_IN", qty=D(1000) + TOL)
    assert not any("ratio disagrees" in p for p in lg.reconcile())
    # the ratio tolerance is TOL x den: with den = 2 a 1e-9 gap passes; a gap of 5e-9 is flagged
    lg = ledger(100000)
    lg.register_conversion(conv(num=D(10), den=D(2)))
    lg.buy(BUY_DAY, OLD, D(100), D(250), D(0), "trade:1")
    lg.apply_conversion(CHANGE, OLD)  # 100 x 10 / 2 = 500
    _edit(lg, "CONVERT_IN", qty=D(500) + D("5e-10"))  # inn x den + out x num = 1e-9: inside TOL x 2
    assert not any("ratio disagrees" in p for p in lg.reconcile())
    _edit(lg, "CONVERT_IN", qty=D(500) + D("5e-9"))
    assert any("ratio disagrees" in p for p in lg.reconcile())

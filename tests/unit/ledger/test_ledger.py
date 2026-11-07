from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from algo.ledger.ledger import (
    TOL,
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

from decimal import Decimal as D

from algo.execution.oms import Mismatch
from algo.execution.reconciler import Portfolio, compare


def test_matching_portfolios_have_no_difference():
    assert compare(Portfolio({7: 10, 8: -5}, D(1000)), Portfolio({7: 10, 8: -5}, D(1000))) == []


def test_a_position_that_differs_or_is_missing_on_either_side_is_named():
    ours, theirs = Portfolio({7: 10, 8: 3}), Portfolio({7: 12, 9: 4})
    assert compare(ours, theirs) == [
        Mismatch("POSITION_MISMATCH", "", "instrument 7: we hold 10, the broker 12"),
        Mismatch("POSITION_MISMATCH", "", "instrument 8: we hold 3, the broker 0"),
        Mismatch("POSITION_MISMATCH", "", "instrument 9: we hold 0, the broker 4"),
    ]


def test_cash_is_compared_only_when_both_sides_know_it_and_beyond_the_tolerance():
    assert compare(Portfolio({}, D(1000)), Portfolio({}, D("1000.9"))) == []  # within a rupee
    assert compare(Portfolio({}, D(1000)), Portfolio({}, None)) == []  # the broker did not say
    assert compare(Portfolio({}, None), Portfolio({}, D(5))) == []  # we did not say
    off = compare(Portfolio({}, D(1000)), Portfolio({}, D(990)))
    assert off == [Mismatch("CASH_MISMATCH", "", "we have 1000, the broker 990")]
    assert compare(Portfolio({}, D(1000)), Portfolio({}, D(990)), cash_tolerance=D(20)) == []


def test_on_an_account_with_shares_bought_by_hand_more_at_the_broker_is_fine_and_less_is_not():
    ours = Portfolio({7: 10, 8: 5})
    theirs = Portfolio(
        {7: 1010, 8: 3, 9: 500}
    )  # 7: 1000 of the owner's own; 8: some of ours are gone; 9: only the owner's
    found = compare(ours, theirs, broker_may_hold_more=True)
    assert [m.detail for m in found] == ["instrument 8: we hold 5, the broker 3"]
    assert len(compare(ours, theirs)) == 3  # the strict comparison reports all three


# ---- found by mutation testing: a position missing on one side counts as exactly zero, the cash boundary, the owner's-shares rule ----
def test_a_zero_position_is_not_a_difference_whichever_side_leaves_it_out():
    assert compare(Portfolio({7: 0}), Portfolio({})) == []
    assert compare(Portfolio({}), Portfolio({7: 0})) == []


def test_a_position_missing_on_one_side_is_a_difference_of_its_whole_size_even_when_that_size_is_one():
    assert [m.detail for m in compare(Portfolio({}), Portfolio({7: 1}))] == [
        "instrument 7: we hold 0, the broker 1"
    ]
    assert [m.detail for m in compare(Portfolio({7: 1}), Portfolio({}))] == [
        "instrument 7: we hold 1, the broker 0"
    ]


def test_with_shares_bought_by_hand_a_missing_position_of_ours_is_fine_only_when_the_broker_holds_more_than_zero():
    assert (
        compare(Portfolio({}), Portfolio({7: 1}), broker_may_hold_more=True) == []
    )  # the owner's own share
    assert [
        m.detail for m in compare(Portfolio({}), Portfolio({7: -1}), broker_may_hold_more=True)
    ] == ["instrument 7: we hold 0, the broker -1"]  # a short we never took
    assert [
        m.detail for m in compare(Portfolio({7: 1}), Portfolio({}), broker_may_hold_more=True)
    ] == ["instrument 7: we hold 1, the broker 0"]  # ours are gone


def test_cash_exactly_at_the_tolerance_is_not_a_difference_and_a_hair_over_is():
    assert compare(Portfolio({}, D(1000)), Portfolio({}, D(1001))) == []
    assert compare(Portfolio({}, D(1000)), Portfolio({}, D("1001.01"))) == [
        Mismatch("CASH_MISMATCH", "", "we have 1000, the broker 1001.01")
    ]

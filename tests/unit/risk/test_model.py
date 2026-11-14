from decimal import Decimal as D

from algo.risk.model import Book, Day, Decision, Market, OrderRequest, Rejection, Side


def test_a_buy_adds_exposure_and_a_sell_removes_it():
    assert (Side.BUY.sign, Side.SELL.sign) == (1, -1)
    assert Side("BUY") is Side.BUY


def test_an_empty_decision_is_an_approval_and_any_rejection_makes_it_a_refusal():
    assert Decision().approved and Decision().codes == []
    d = Decision((Rejection("A", "a"), Rejection("B", "b")))
    assert not d.approved and d.codes == ["A", "B"]


def test_the_defaults_describe_an_empty_book_and_a_quiet_day_and_an_order_is_a_market_order_unless_priced():
    assert Book() == Book(0, D(0), D(0), D(0), D(0), D(0), 0) and Day() == Day(0, D(0), D(0), 0)
    assert Market(ltp=D(10)).tradable and Market(ltp=D(10)).adv is None
    o = OrderRequest("s", 1, Side.BUY, 5)
    assert o.price is None and o.reduce_only is False

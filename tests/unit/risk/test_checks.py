from datetime import UTC, datetime, time
from decimal import Decimal as D

import pytest

from algo.risk.checks import check
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 10:30 IST
BOOK0, DAY0 = Book(), Day()
MKT = Market(ltp=D(100), adv=1_000_000, sector="IT")


def buy(qty=10, price=None, **kw):
    return OrderRequest("s1", 7, Side.BUY, qty, price, **kw)


def sell(qty=10, price=None, **kw):
    return OrderRequest("s1", 7, Side.SELL, qty, price, **kw)


def run(order, limits=None, market=MKT, book=BOOK0, day=DAY0, now=NOW):
    return check(order, market, book, day, limits or Limits(), now).codes


def test_an_order_with_no_limits_set_is_approved():
    d = check(buy(), MKT, Book(), Day(), Limits(), NOW)
    assert d.approved and d.rejections == ()


def test_a_non_positive_quantity_is_always_refused():
    assert run(buy(0)) == ["BAD_QTY"] and run(buy(-5)) == ["BAD_QTY"]


def test_restricted_and_allow_list():
    assert run(buy(), Limits(restricted=frozenset({7}))) == ["RESTRICTED"]
    assert run(buy(), Limits(restricted=frozenset({8}))) == []
    assert run(buy(), Limits(allowed=frozenset({1}))) == ["NOT_ALLOWED"]
    assert run(buy(), Limits(allowed=frozenset({7}))) == []
    assert run(buy(), Limits(allowed=frozenset({7}), restricted=frozenset({7}))) == [
        "RESTRICTED"
    ]  # restriction wins... and the list passes


def test_an_instrument_that_cannot_trade_is_refused():
    assert run(buy(), market=Market(ltp=D(100), tradable=False)) == ["NOT_TRADABLE"]


def test_trading_hours_are_indian_time_and_inclusive():
    lim = Limits(trading_hours=(time(9, 15), time(15, 30)))
    at = lambda h, m: datetime(2026, 11, 16, h, m, tzinfo=UTC)  # noqa: E731
    assert run(buy(), lim, now=at(3, 45)) == []  # 09:15 IST exactly
    assert run(buy(), lim, now=at(10, 0)) == []  # 15:30 IST exactly
    assert run(buy(), lim, now=at(3, 44)) == ["HOURS"]  # 09:14
    assert run(buy(), lim, now=at(10, 1)) == ["HOURS"]  # 15:31


@pytest.mark.parametrize(
    ("limits", "ok", "bad", "code"),
    [
        (Limits(max_order_qty=10), buy(10), buy(11), "MAX_QTY"),
        (Limits(max_order_value=D(1000)), buy(10), buy(11), "MAX_VALUE"),
        (Limits(max_adv_fraction=D("0.00001")), buy(10), buy(11), "ADV"),  # 10 shares of 1,000,000
    ],
)
def test_size_caps_have_an_exact_boundary(limits, ok, bad, code):
    assert run(ok, limits) == [] and run(bad, limits) == [code]


def test_the_order_value_uses_the_limit_price_when_there_is_one():
    lim = Limits(max_order_value=D(1000))
    assert run(buy(10, D("100")), lim) == []
    assert run(buy(10, D("100.01")), lim) == ["MAX_VALUE"]


def test_a_missing_adv_cannot_be_checked_so_it_is_refused():
    lim = Limits(max_adv_fraction=D("0.1"))
    assert run(buy(), lim, market=Market(ltp=D(100), adv=None)) == ["ADV_UNKNOWN"]


def test_fat_finger_band_applies_to_limit_prices_only_and_is_exact():
    lim = Limits(fat_finger_band=D("0.05"))
    assert run(buy(1, D("105")), lim) == [] and run(buy(1, D("95")), lim) == []
    assert run(buy(1, D("105.01")), lim) == ["FAT_FINGER"] and run(buy(1, D("94.99")), lim) == [
        "FAT_FINGER"
    ]
    assert run(buy(1), lim) == []  # a market order has no price to be fat about


def test_exposure_limits_are_measured_after_the_order_and_are_exact():
    book = Book(
        instrument_value=D(9000), sector_value=D(20000), gross_value=D(50000), net_value=D(30000)
    )
    # buying 10 at 100 adds 1000: instrument 10000, sector 21000, gross 51000, net 31000
    assert run(buy(), Limits(max_instrument_value=D(10000)), book=book) == []
    assert run(buy(), Limits(max_instrument_value=D("9999.99")), book=book) == ["INSTRUMENT_LIMIT"]
    assert run(buy(), Limits(max_sector_value=D(21000)), book=book) == []
    assert run(buy(), Limits(max_sector_value=D(20999)), book=book) == ["SECTOR_LIMIT"]
    assert run(buy(), Limits(max_gross_value=D(51000)), book=book) == []
    assert run(buy(), Limits(max_gross_value=D(50999)), book=book) == ["GROSS_LIMIT"]
    assert run(buy(), Limits(max_net_value=D(31000)), book=book) == []
    assert run(buy(), Limits(max_net_value=D(30999)), book=book) == ["NET_LIMIT"]


def test_a_sale_that_reduces_exposure_passes_limits_it_would_have_broken_as_a_buy():
    book = Book(
        position_qty=100,
        instrument_value=D(10000),
        sector_value=D(10000),
        gross_value=D(10000),
        net_value=D(10000),
    )
    lim = Limits(
        max_instrument_value=D(9000),
        max_sector_value=D(9000),
        max_gross_value=D(9000),
        max_net_value=D(9000),
    )
    assert run(sell(), lim, book=book) == []  # 9,000 after: exactly at every limit
    assert run(sell(5), lim, book=book) == [
        "INSTRUMENT_LIMIT",
        "SECTOR_LIMIT",
        "GROSS_LIMIT",
        "NET_LIMIT",
    ]


def test_a_short_sale_adds_gross_exposure():
    lim = Limits(max_gross_value=D(999))
    assert run(sell(), lim, book=Book()) == ["GROSS_LIMIT"]  # opens a 1,000 short


def test_the_sector_limit_needs_to_know_the_sector():
    lim = Limits(max_sector_value=D(1))
    assert run(buy(), lim, market=Market(ltp=D(100), sector=None)) == ["SECTOR_UNKNOWN"]


def test_margin_only_matters_for_buys_when_switched_on():
    lim = Limits(check_margin=True)
    assert run(buy(), lim, book=Book(margin_available=D(1000))) == []  # costs exactly 1,000
    assert run(buy(), lim, book=Book(margin_available=D("999.99"))) == ["MARGIN"]
    assert run(sell(), lim, book=Book(margin_available=D(0), position_qty=10)) == []
    assert run(buy(), Limits(), book=Book(margin_available=D(0))) == []  # not switched on


def test_open_order_count_daily_counts_turnover_loss_and_failures_have_exact_boundaries():
    assert run(buy(), Limits(max_open_orders=5), book=Book(open_orders=4)) == []
    assert run(buy(), Limits(max_open_orders=5), book=Book(open_orders=5)) == ["OPEN_ORDERS"]
    assert run(buy(), Limits(max_daily_orders=3), day=Day(orders=2)) == []
    assert run(buy(), Limits(max_daily_orders=3), day=Day(orders=3)) == ["DAILY_ORDERS"]
    assert (
        run(buy(), Limits(max_daily_turnover=D(5000)), day=Day(turnover=D(4000))) == []
    )  # 4,000 + 1,000
    assert run(buy(), Limits(max_daily_turnover=D(5000)), day=Day(turnover=D("4000.01"))) == [
        "DAILY_TURNOVER"
    ]
    assert run(buy(), Limits(max_daily_loss=D(2500)), day=Day(pnl=D("-2499.99"))) == []
    assert run(buy(), Limits(max_daily_loss=D(2500)), day=Day(pnl=D(-2500))) == ["DAILY_LOSS"]
    assert run(buy(), Limits(max_consecutive_failures=3), day=Day(consecutive_failures=2)) == []
    assert run(buy(), Limits(max_consecutive_failures=3), day=Day(consecutive_failures=3)) == [
        "CONSEC_FAILURES"
    ]


def test_every_breach_is_reported_not_just_the_first():
    lim = Limits(max_order_qty=1, max_order_value=D(1), restricted=frozenset({7}))
    assert run(buy(), lim) == ["RESTRICTED", "MAX_QTY", "MAX_VALUE"]
    d = check(buy(), MKT, Book(), Day(), lim, NOW)
    assert not d.approved and "10" in d.rejections[1].detail


def test_a_reduce_only_order_must_shrink_the_position_and_skips_exposure_and_daily_limits():
    lim = Limits(
        max_daily_loss=D(1),
        max_daily_orders=1,
        max_open_orders=1,
        check_margin=True,
        max_gross_value=D(1),
    )
    bad_day, bad_book = (
        Day(orders=9, pnl=D(-99), consecutive_failures=9),
        Book(position_qty=10, open_orders=9),
    )
    assert (
        run(sell(10, reduce_only=True), lim, book=bad_book, day=bad_day) == []
    )  # closing: allowed even in a loss
    assert run(sell(4, reduce_only=True), lim, book=bad_book, day=bad_day) == []
    assert run(sell(11, reduce_only=True), lim, book=bad_book) == [
        "REDUCE_ONLY_VIOLATION"
    ]  # would flip
    assert run(buy(5, reduce_only=True), lim, book=bad_book) == [
        "REDUCE_ONLY_VIOLATION"
    ]  # wrong side
    short = Book(position_qty=-10)
    assert run(buy(10, reduce_only=True), lim, book=short) == []
    assert run(sell(1, reduce_only=True), lim, book=Book()) == [
        "REDUCE_ONLY_VIOLATION"
    ]  # nothing to reduce
    assert run(sell(10, reduce_only=True), Limits(restricted=frozenset({7})), book=bad_book) == [
        "RESTRICTED"
    ]


# ---- found by mutation testing: what each refusal SAYS (an operator reads these), and the boundaries around reducing orders ----
def why(order, limits=None, market=MKT, book=BOOK0, day=DAY0, now=NOW):
    d = check(order, market, book, day, limits or Limits(), now)
    return [(r.code, r.detail) for r in d.rejections]


def test_every_refusal_says_in_exact_words_what_was_wrong():
    L = Limits
    assert why(buy(0)) == [("BAD_QTY", "quantity 0 is not positive")]
    assert why(buy(), L(restricted=frozenset({7}))) == [
        ("RESTRICTED", "instrument 7 is restricted")
    ]
    assert why(buy(), L(allowed=frozenset({1}))) == [
        ("NOT_ALLOWED", "instrument 7 is not on the allow-list")
    ]
    assert why(buy(), market=Market(ltp=D(100), tradable=False)) == [
        ("NOT_TRADABLE", "the instrument is not tradable now (expired, suspended or halted)")
    ]
    assert why(
        buy(),
        L(trading_hours=(time(9, 15), time(15, 30))),
        now=datetime(2026, 11, 16, 11, 0, tzinfo=UTC),
    ) == [("HOURS", "16:30 IST is outside 09:15-15:30")]
    assert why(buy(11), L(max_order_qty=10)) == [("MAX_QTY", "11 shares is over 10")]
    assert why(buy(11), L(max_order_value=D(1000))) == [
        ("MAX_VALUE", "order value 1100 is over 1000")
    ]
    assert why(buy(), L(max_adv_fraction=D("0.00001")), market=Market(ltp=D(100), adv=None)) == [
        ("ADV_UNKNOWN", "average daily volume is not known, so the size cannot be checked")
    ]
    assert why(buy(11), L(max_adv_fraction=D("0.00001"))) == [
        ("ADV", "11 shares is over 0.00001 of the average daily volume 1000000")
    ]
    assert why(buy(10, D("120")), L(fat_finger_band=D("0.1"))) == [
        ("FAT_FINGER", "limit 120 is more than 0.1 from the last price 100")
    ]
    assert why(buy(10), L(max_instrument_value=D(500))) == [
        ("INSTRUMENT_LIMIT", "position would be 1000, over 500")
    ]
    assert why(buy(10), L(max_sector_value=D(500)), market=Market(ltp=D(100), sector=None)) == [
        ("SECTOR_UNKNOWN", "the sector is not known, so the sector limit cannot be checked")
    ]
    assert why(buy(10), L(max_sector_value=D(500)), book=Book(sector_value=D(100))) == [
        ("SECTOR_LIMIT", "sector exposure would be 1100, over 500")
    ]
    assert why(sell(10), L(max_sector_value=D(500)), book=Book(sector_value=D(-100))) == [
        ("SECTOR_LIMIT", "sector exposure would be 1100, over 500")
    ]  # a short adds exposure
    assert why(buy(10), L(max_gross_value=D(500)), book=Book(gross_value=D(100))) == [
        ("GROSS_LIMIT", "gross exposure would be 1100, over 500")
    ]
    assert why(buy(10), L(max_net_value=D(500)), book=Book(net_value=D(100))) == [
        ("NET_LIMIT", "net exposure would be 1100, over 500")
    ]
    assert why(sell(10), L(max_net_value=D(500)), book=Book(net_value=D(-100))) == [
        ("NET_LIMIT", "net exposure would be 1100, over 500")
    ]
    assert why(buy(10), L(check_margin=True), book=Book(margin_available=D(10))) == [
        ("MARGIN", "the order needs 1000, margin available is 10")
    ]
    assert why(buy(), L(max_open_orders=3), book=Book(open_orders=3)) == [
        ("OPEN_ORDERS", "3 orders are already open (limit 3)")
    ]
    assert why(buy(), L(max_daily_orders=5), day=Day(orders=5)) == [
        ("DAILY_ORDERS", "5 orders today (limit 5)")
    ]
    assert why(buy(10), L(max_daily_turnover=D(1500)), day=Day(turnover=D(600))) == [
        ("DAILY_TURNOVER", "turnover would be 1600, over 1500")
    ]
    assert why(buy(), L(max_daily_loss=D(500)), day=Day(pnl=D(-500))) == [
        ("DAILY_LOSS", "today's loss 500 has reached 500")
    ]
    assert why(buy(), L(max_consecutive_failures=3), day=Day(consecutive_failures=3)) == [
        ("CONSEC_FAILURES", "3 execution failures in a row (limit 3)")
    ]


def test_the_trading_hours_are_read_in_indian_time_whatever_the_machine_clock_says(monkeypatch):
    import time as _time

    monkeypatch.setenv("TZ", "UTC")
    _time.tzset()
    try:
        lim = Limits(trading_hours=(time(9, 15), time(15, 30)))
        assert (
            run(buy(), lim, now=datetime(2026, 11, 16, 5, 0, tzinfo=UTC)) == []
        )  # 10:30 IST (05:00 UTC) is inside
        assert run(buy(), lim, now=datetime(2026, 11, 16, 10, 5, tzinfo=UTC)) == [
            "HOURS"
        ]  # 15:35 IST is after the close; local time here would be 10:05
    finally:
        monkeypatch.delenv("TZ")
        _time.tzset()


def test_a_reduce_only_order_of_one_share_is_a_reduction_and_a_zero_share_one_is_refused_twice_over():
    assert run(sell(1, reduce_only=True), book=Book(position_qty=1)) == []
    assert run(buy(1, reduce_only=True), book=Book(position_qty=-1)) == []
    assert run(sell(0, reduce_only=True), book=Book(position_qty=5)) == [
        "BAD_QTY",
        "REDUCE_ONLY_VIOLATION",
    ]
    assert run(buy(0, reduce_only=True), book=Book(position_qty=-5)) == [
        "BAD_QTY",
        "REDUCE_ONLY_VIOLATION",
    ]
    assert why(sell(6, reduce_only=True), book=Book(position_qty=5)) == [
        ("REDUCE_ONLY_VIOLATION", "a SELL of 6 does not reduce a position of 5")
    ]

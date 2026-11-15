from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from algo.risk.engine import RiskEngine, TokenBucket
from algo.risk.killswitch import KillSwitch
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
BOOK0, DAY0 = Book(), Day()
MKT = Market(ltp=D(100))


def order(**kw):
    return OrderRequest("s1", 7, kw.pop("side", Side.BUY), kw.pop("qty", 10), None, **kw)


def approve(engine, o, now=NOW, book=BOOK0, day=DAY0):
    return engine.approve(o, MKT, book, day, now)


def test_the_token_bucket_has_a_burst_and_refills_at_its_rate():
    b = TokenBucket(rate_per_s=D(2), burst=3, now=NOW)
    assert [b.take(NOW) for _ in range(4)] == [True, True, True, False]  # burst of three
    assert b.take(NOW + timedelta(milliseconds=499)) is False  # not yet one token
    assert b.take(NOW + timedelta(milliseconds=500)) is True  # exactly one token at 2/s
    assert b.take(NOW + timedelta(seconds=60)) is True
    assert [b.take(NOW + timedelta(seconds=60)) for _ in range(3)] == [
        True,
        True,
        False,
    ]  # capped at the burst


def test_an_engine_with_no_rate_limit_never_throttles():
    e = RiskEngine(Limits(), KillSwitch())
    assert all(approve(e, order()).approved for _ in range(100))


def test_the_rate_limit_rejects_the_order_over_the_burst_and_allows_it_again_later():
    e = RiskEngine(Limits(order_rate_per_s=D(5), order_burst=2), KillSwitch())
    assert approve(e, order()).approved and approve(e, order()).approved
    assert approve(e, order()).codes == ["RATE"]
    assert approve(
        e, order(), now=NOW + timedelta(milliseconds=200)
    ).approved  # one token back at 5/s


def test_a_rejected_order_does_not_spend_a_rate_token():
    e = RiskEngine(Limits(order_rate_per_s=D(1), order_burst=1, max_order_qty=5), KillSwitch())
    assert approve(e, order(qty=10)).codes == ["MAX_QTY"]
    assert approve(e, order(qty=5)).approved  # the token was still there


def test_a_paused_strategy_gets_nothing_through_not_even_a_reduce_only_order():
    k = KillSwitch()
    e = RiskEngine(Limits(), k)
    k.pause("s1", by="jane", reason="r", now=NOW)
    assert approve(e, order()).codes == ["PAUSED"]
    assert approve(
        e, order(side=Side.SELL, reduce_only=True), book=Book(position_qty=10)
    ).codes == ["PAUSED"]
    other = OrderRequest("s2", 7, Side.BUY, 1)
    assert e.approve(other, MKT, Book(), Day(), NOW).approved  # only that strategy


def test_flatten_lets_only_closing_orders_through():
    k = KillSwitch()
    e = RiskEngine(Limits(), k)
    k.flatten(None, by="jane", reason="fire", now=NOW, emergency_override=True)
    assert approve(e, order()).codes == ["PAUSED"]  # a new position is still refused
    closing = order(side=Side.SELL, reduce_only=True)
    assert approve(e, closing, book=Book(position_qty=10)).approved
    assert approve(e, closing, book=Book(position_qty=3)).codes == [
        "REDUCE_ONLY_VIOLATION"
    ]  # and it must really close


def test_every_reason_is_reported_together():
    k = KillSwitch()
    e = RiskEngine(Limits(max_order_qty=1), k)
    k.pause(None, by="jane", reason="r", now=NOW)
    assert approve(e, order()).codes == ["PAUSED", "MAX_QTY"]


# ---- found by mutation testing ------------------------------------------------------------------------------------
def test_the_pause_and_rate_refusals_say_in_exact_words_what_stopped_the_order():
    k = KillSwitch()
    e = RiskEngine(Limits(order_rate_per_s=D(1), order_burst=1), k)
    k.pause("s1", by="jane", reason="r", now=NOW)
    assert [(r.code, r.detail) for r in approve(e, order()).rejections] == [
        ("PAUSED", "the kill switch is PAUSE for s1")
    ]
    k.resume("s1", by="jane", reason="ok", now=NOW)
    assert approve(e, order()).approved  # the only token
    assert [(r.code, r.detail) for r in approve(e, order()).rejections] == [
        ("RATE", "more than 1 orders a second")
    ]


def test_the_day_and_the_time_reach_the_checks_not_just_the_order():
    e = RiskEngine(
        Limits(
            max_daily_orders=1,
            trading_hours=(
                NOW.time().replace(hour=9, minute=15),
                NOW.time().replace(hour=15, minute=30),
            ),
        ),
        KillSwitch(),
    )
    assert approve(e, order(), day=Day(orders=1)).codes == [
        "DAILY_ORDERS"
    ]  # the day's activity is used
    late = NOW.replace(hour=11)  # 16:30 IST
    assert approve(e, order(), now=late).codes == ["HOURS"]  # and so is the clock

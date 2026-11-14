"""Risk limits and the kill switch in the paper path: enforced when an order is approved and when it would fill."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from algo.backtest.costs.policy import CostModel
from algo.core.clock import SimClock
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.paper import book, orders
from algo.paper import risk as paper_risk
from algo.risk import store
from algo.risk.limits import LimitsError
from tests.support.portal import add_user

pytestmark = pytest.mark.integration
COST = CostModel("test-flat", D(10), D(0), False)
OPEN = datetime(2026, 11, 13, 3, 45, tzinfo=UTC)  # Friday 09:15 IST
CLOSE = OPEN + timedelta(hours=6, minutes=15)
EVENING = OPEN - timedelta(hours=8)


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "AAA")
    jane = add_user(conn, SimClock(EVENING), "TRADER", "jane@example.com")
    book.create_account(
        conn,
        jane,
        strategy_id="trend_pullback",
        params={},
        initial_cash=D(100_000),
        started_on=date(2026, 11, 2),
        now=EVENING,
    )
    return conn, jane, iid


def propose(conn, user, iid, side="BUY", qty=100, ref=D(200)):
    return conn.execute(
        "INSERT INTO paper_order (user_id, decision_day, instrument_id, side, qty, ref_price, reason, created_at, not_before, expires_at)"
        " VALUES (%s,%s,%s,%s,%s,%s,'entry',%s,%s,%s) RETURNING order_id",
        (user, date(2026, 11, 12), iid, side, qty, ref, EVENING, OPEN, CLOSE),
    ).fetchone()[0]


def approve(conn, user, oid):
    orders.approve(conn, oid, user_id=user, now=EVENING)


def status(conn, oid):
    return conn.execute(
        "SELECT status, failure FROM paper_order WHERE order_id=%s", (oid,)
    ).fetchone()


def hold(conn, user, iid, qty, price):
    book.record_fill(
        conn,
        user,
        day=date(2026, 11, 12),
        side="BUY",
        iid=iid,
        qty=D(qty),
        price=D(price),
        commission=D(0),
        charges=[],
        ref="seed",
        now=EVENING,
    )


def live_bar(conn, iid, n, price):
    t = OPEN + timedelta(minutes=n)
    conn.execute(
        "INSERT INTO live_bar_1m (instrument_id, ts, open, high, low, close, volume, ticks, partial, built_at) VALUES (%s,%s,%s,%s,%s,%s,1000,5,false,%s)",
        (iid, t, price, price, price, price, t),
    )


def test_an_account_with_no_limits_is_not_limited_and_limits_are_validated_when_set(env):
    conn, jane, iid = env
    assert paper_risk.get_limits(conn, jane) == paper_risk.Limits()
    approve(conn, jane, propose(conn, jane, iid, qty=1_000_000))  # nothing set, nothing checked
    paper_risk.set_limits(
        conn, jane, {"max_order_value": "10000", "trading_hours": ["09:15", "15:30"]}
    )
    assert paper_risk.get_limits(conn, jane).max_order_value == D(10000)
    with pytest.raises(LimitsError, match="unknown limit"):
        paper_risk.set_limits(conn, jane, {"max_order_valu": 1})
    assert paper_risk.get_limits(conn, jane).max_order_value == D(
        10000
    )  # the bad update changed nothing
    paper_risk.set_limits(conn, jane, None)
    assert paper_risk.get_limits(conn, jane) == paper_risk.Limits()


def test_an_order_that_breaches_a_limit_cannot_be_approved_and_stays_pending_with_the_reasons(env):
    conn, jane, iid = env
    paper_risk.set_limits(conn, jane, {"max_order_value": 10000})
    big, small = (
        propose(conn, jane, iid, qty=100),
        propose(conn, jane, iid, qty=50),
    )  # 20,000 and 10,000
    with pytest.raises(orders.OrderError, match="risk: MAX_VALUE"):
        approve(conn, jane, big)
    assert status(conn, big) == ("PENDING", None)
    approve(conn, jane, small)  # exactly at the limit
    assert status(conn, small)[0] == "APPROVED"


def test_exposure_is_measured_against_what_the_account_already_holds(env):
    conn, jane, iid = env
    hold(conn, jane, iid, 50, 200)  # 10,000 at cost
    paper_risk.set_limits(conn, jane, {"max_instrument_value": 29999, "max_gross_value": 29999})
    with pytest.raises(orders.OrderError, match="INSTRUMENT_LIMIT, GROSS_LIMIT"):
        approve(conn, jane, propose(conn, jane, iid, qty=100))  # 10,000 + 20,000
    approve(conn, jane, propose(conn, jane, iid, qty=99))  # 29,800
    paper_risk.set_limits(
        conn, jane, {"max_instrument_value": 1}
    )  # a sale is exempt from exposure limits
    approve(conn, jane, propose(conn, jane, iid, side="SELL", qty=50))


def test_a_sale_must_reduce_what_the_account_holds(env):
    conn, jane, iid = env
    hold(conn, jane, iid, 50, 200)
    with pytest.raises(orders.OrderError, match="REDUCE_ONLY_VIOLATION"):
        approve(conn, jane, propose(conn, jane, iid, side="SELL", qty=51))
    approve(conn, jane, propose(conn, jane, iid, side="SELL", qty=50))


def test_approved_orders_count_as_open_orders_and_a_fractional_quantity_is_refused(env):
    conn, jane, iid = env
    paper_risk.set_limits(conn, jane, {"max_open_orders": 1})
    approve(conn, jane, propose(conn, jane, iid, qty=10))
    with pytest.raises(orders.OrderError, match="OPEN_ORDERS"):
        approve(conn, jane, propose(conn, jane, iid, qty=10))
    oid = propose(conn, jane, iid, qty=10)
    conn.execute("UPDATE paper_order SET qty=10.5 WHERE order_id=%s", (oid,))
    with pytest.raises(orders.OrderError, match="whole number"):
        approve(conn, jane, oid)


def test_daily_counts_and_turnover_come_from_todays_approved_orders(env):
    conn, jane, iid = env
    paper_risk.set_limits(conn, jane, {"max_daily_orders": 2, "max_daily_turnover": 40000})
    approve(conn, jane, propose(conn, jane, iid, qty=100))  # 20,000
    approve(conn, jane, propose(conn, jane, iid, qty=50))  # 10,000 more
    with pytest.raises(orders.OrderError, match="DAILY_ORDERS"):
        approve(conn, jane, propose(conn, jane, iid, qty=1))
    paper_risk.set_limits(conn, jane, {"max_daily_turnover": 30000})
    with pytest.raises(orders.OrderError, match="DAILY_TURNOVER"):
        approve(conn, jane, propose(conn, jane, iid, qty=1))  # 30,000 + 200


def test_a_paused_strategy_cannot_have_orders_approved_until_it_is_resumed(env):
    conn, jane, iid = env
    oid = propose(conn, jane, iid)
    store.change(conn, "pause", "trend_pullback", by="jane", reason="looking", now=EVENING)
    with pytest.raises(orders.OrderError, match="risk: PAUSED"):
        approve(conn, jane, oid)
    store.change(conn, "resume", "trend_pullback", by="jane", reason="ok", now=EVENING)
    approve(conn, jane, oid)
    other = propose(conn, jane, iid)
    store.change(
        conn, "pause", None, by="joe", reason="global", now=EVENING
    )  # global covers every strategy
    with pytest.raises(orders.OrderError, match="PAUSED"):
        approve(conn, jane, other)


def test_cancel_fails_the_approved_orders_that_have_not_filled_and_pause_leaves_them_to_fill(env):
    conn, jane, iid = env
    first, second = propose(conn, jane, iid, qty=10), propose(conn, jane, iid, qty=10)
    approve(conn, jane, first)
    approve(conn, jane, second)
    live_bar(conn, iid, 0, 200)
    store.change(conn, "pause", "trend_pullback", by="jane", reason="no new orders", now=EVENING)
    report = orders.fill_due(conn, OPEN + timedelta(minutes=5), cost=COST, slippage_bps=D(0))
    assert (report.filled, report.failed) == (
        2,
        0,
    )  # PAUSE stops new orders, not the ones already sent
    third = propose(conn, jane, iid, qty=10)
    store.change(conn, "resume", "trend_pullback", by="jane", reason="ok", now=EVENING)
    approve(conn, jane, third)
    store.change(conn, "cancel", "trend_pullback", by="jane", reason="data problem", now=EVENING)
    report = orders.fill_due(conn, OPEN + timedelta(minutes=5), cost=COST, slippage_bps=D(0))
    assert (report.filled, report.failed) == (0, 1)
    assert status(conn, third) == ("FAILED", "cancelled by the kill switch: data problem")

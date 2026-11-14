from decimal import Decimal as D

import pytest

from algo.core.clock import SimClock
from algo.execution.broker import BrokerError, BrokerRejected, BrokerTimeout
from algo.execution.kite_broker import BASE, KiteBroker
from algo.execution.live_gate import LiveGate, LiveRefused, open_gate
from algo.execution.oms import Oms
from algo.execution.orders import State, client_order_id
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_kite import FakeKite

GATE = open_gate({"ALGO_LIVE": "1"}, "LIVE", True)
SYMBOLS = {7: "INFY", 8: "TCS"}
TAG = client_order_id("s1", "k1")
BUY = OrderRequest("s1", 7, Side.BUY, 10)


def broker(kite=None, gate=GATE):
    kite = kite or FakeKite()
    return KiteBroker("KEY", "TOKEN", kite, SYMBOLS, gate=gate), kite


def test_it_will_not_start_without_an_open_live_gate():
    with pytest.raises(LiveRefused, match="gate"):
        KiteBroker("KEY", "TOKEN", FakeKite(), SYMBOLS, gate=LiveGate(open=False))


def test_a_market_order_is_sent_as_a_delivery_order_tagged_with_the_client_order_id():
    b, kite = broker()
    assert b.place_order(BUY, TAG) == "220000000000"
    ((method, url, headers, data),) = kite.calls
    assert (method, url) == ("POST", f"{BASE}/orders/regular")
    assert headers == {"X-Kite-Version": "3", "Authorization": "token KEY:TOKEN"}
    assert data == {
        "exchange": "NSE",
        "tradingsymbol": "INFY",
        "transaction_type": "BUY",
        "quantity": "10",
        "product": "CNC",
        "order_type": "MARKET",
        "market_protection": "1",  # Kite rejects API market orders without it; 1% band
        "validity": "DAY",
        "tag": TAG,
    }
    assert len(TAG) == 20 and TAG.isalnum()  # Kite's tag limit


def test_a_priced_order_is_a_limit_order_and_a_sale_says_sell():
    b, kite = broker()
    b.place_order(OrderRequest("s1", 8, Side.SELL, 3, D("3500.50")), TAG)
    data = kite.calls[0][3]
    assert (data["order_type"], data["price"], data["transaction_type"], data["tradingsymbol"]) == (
        "LIMIT",
        "3500.50",
        "SELL",
        "TCS",
    )
    assert "market_protection" not in data  # it only applies to MARKET and SL-M


@pytest.mark.parametrize("behaviour", ["timeout_before", "timeout_after", "http500"])
def test_no_answer_and_server_errors_are_ambiguous_never_a_rejection(behaviour):
    b, kite = broker(FakeKite([behaviour]))
    with pytest.raises(BrokerTimeout):
        b.place_order(BUY, TAG)
    assert len(kite.calls) == 1  # never retried inside the broker


@pytest.mark.parametrize(
    ("behaviour", "text"), [("429", "rate"), ("403", "session"), ("400", "Insufficient funds")]
)
def test_an_answer_that_says_it_was_not_placed_is_a_rejection_with_the_reason(behaviour, text):
    b, _ = broker(FakeKite([behaviour]))
    with pytest.raises(BrokerRejected, match=text):
        b.place_order(BUY, TAG)


def test_an_instrument_with_no_kite_symbol_is_refused_before_anything_is_sent():
    b, kite = broker()
    with pytest.raises(BrokerRejected, match="no Kite symbol"):
        b.place_order(OrderRequest("s1", 99, Side.BUY, 1), TAG)
    assert kite.calls == []


def test_an_odd_success_reply_is_ambiguous():
    class Odd:
        def __call__(self, method, url, headers, data=None):
            return 200, b'{"status": "success", "data": {}}'

    with pytest.raises(BrokerTimeout, match="no order id"):
        KiteBroker("KEY", "TOKEN", Odd(), SYMBOLS, gate=GATE).place_order(BUY, TAG)


def test_cancelling_names_the_order_and_failures_are_told_apart():
    b, kite = broker()
    b.cancel_order("2200")
    assert kite.calls[-1][:2] == ("DELETE", f"{BASE}/orders/regular/2200")
    kite.delete_status = 400
    with pytest.raises(BrokerError, match="cannot be cancelled"):
        b.cancel_order("2200")
    kite.delete_status = 0
    with pytest.raises(BrokerTimeout):
        b.cancel_order("2200")


def test_the_order_book_is_read_with_our_tags_and_kites_statuses_mapped():
    b, kite = broker()
    for tag in ("A", "B", "C", "D", "E"):
        b.place_order(BUY, tag)
    ids = [o["order_id"] for o in kite.book]
    kite.move(ids[1], "COMPLETE", 10, 1500.5)
    kite.move(ids[2], "REJECTED", 0, 0, "RMS: margin exceeded")
    kite.move(ids[3], "CANCELLED")
    kite.move(ids[4], "OPEN", 4, 1499.0)  # partly filled and still open
    kite.book.append(
        {
            "order_id": "999",
            "tag": None,
            "status": "TRIGGER PENDING",
            "filled_quantity": 0,
            "average_price": 0,
            "status_message": None,
        }
    )  # placed by hand
    got = {o.client_order_id: o for o in b.orders()}
    assert (
        got["A"].status == "OPEN"
        and got["B"].status == "COMPLETE"
        and (got["B"].filled_qty, got["B"].avg_price) == (10, D("1500.5"))
    )
    assert got["C"].status == "REJECTED" and got["C"].reason == "RMS: margin exceeded"
    assert (
        got["D"].status == "CANCELLED" and got["E"].status == "PARTIAL" and got["E"].filled_qty == 4
    )
    assert got["MANUAL-999"].status == "OPEN" and got["A"].broker_order_id == ids[0]


def test_reading_the_order_book_fails_loudly():
    b, kite = broker()
    kite.get_status = 0
    with pytest.raises(BrokerTimeout):
        b.orders()
    kite.get_status = 500
    with pytest.raises(BrokerError, match="HTTP 500"):
        b.orders()


def oms_with(kite):
    sw = KillSwitch()
    return Oms(
        KiteBroker("KEY", "TOKEN", kite, SYMBOLS, gate=GATE),
        RiskEngine(Limits(), sw),
        SimClock(
            __import__("datetime").datetime(2026, 11, 16, 5, 0, tzinfo=__import__("datetime").UTC)
        ),
    ), sw


def test_through_the_oms_a_lost_reply_never_becomes_a_second_order():
    kite = FakeKite(["timeout_after"])  # Kite took the order; the answer never came back
    oms, sw = oms_with(kite)
    first = oms.submit("k1", BUY, Market(ltp=D(1500)), Book(), Day())
    assert first.state is State.UNKNOWN
    again = oms.submit(
        "k1", BUY, Market(ltp=D(1500)), Book(), Day()
    )  # the same intent: looked up by its tag
    assert again.state is State.ACKED and again.broker_order_id == "220000000000"
    posts = [c for c in kite.calls if c[0] == "POST"]
    assert len(posts) == 1 and len(kite.book) == 1  # one order at the exchange, one POST ever sent
    assert oms.reconcile() == []


def test_through_the_oms_an_order_that_never_arrived_stays_unknown_and_pauses_the_strategy():
    kite = FakeKite(["timeout_before"])
    oms, sw = oms_with(kite)
    oms.submit("k1", BUY, Market(ltp=D(1500)), Book(), Day())
    assert oms.submit("k1", BUY, Market(ltp=D(1500)), Book(), Day()).state is State.UNKNOWN
    assert (
        len([c for c in kite.calls if c[0] == "POST"]) == 1
        and sw.mode("s1").value == "PAUSE"
        and oms.alerts
    )


def test_an_error_reply_that_is_not_json_is_still_reported():
    def html(method, url, headers, data=None):
        return 400, b"<html>Bad Request: the gateway says no</html>"

    with pytest.raises(BrokerRejected, match="Bad Request"):
        KiteBroker("KEY", "TOKEN", html, SYMBOLS, gate=GATE).place_order(BUY, TAG)
    with pytest.raises(BrokerError, match="gateway says no"):
        KiteBroker("KEY", "TOKEN", html, SYMBOLS, gate=GATE).cancel_order("1")


FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "kite_portfolio"


def read_fixture(name):
    return __import__("json").loads((FIXTURES / f"{name}.json").read_text())["data"]


def account(**over):
    """Kite's three account endpoints, in the shapes recorded from the real API (values made up)."""
    kite = FakeKite()
    kite.reads = {
        "/portfolio/holdings": read_fixture("holdings"),
        "/portfolio/positions": read_fixture("positions"),
        "/user/margins": read_fixture("margins"),
        **over,
    }
    return KiteBroker("KEY", "TOKEN", kite, {7: "AAA", 8: "BBB", 9: "CCC"}, gate=GATE), kite


def test_holdings_are_settled_plus_unsettled_shares_for_the_instruments_we_trade_only():
    b, kite = account()
    assert b.holdings() == {
        7: 100,
        8: 15,
    }  # BBB: 10 settled + 5 bought today, not yet settled; CCC is not held
    assert kite.calls[0][:2] == ("GET", f"{BASE}/portfolio/holdings")  # read only
    other = [{**h, "tradingsymbol": "ZZZ"} for h in read_fixture("holdings")]
    other.append({**read_fixture("holdings")[0], "exchange": "BSE"})
    assert (
        account(**{"/portfolio/holdings": other})[0].holdings() == {}
    )  # not ours, or another exchange


def test_todays_delivery_positions_count_only_our_product_exchange_and_symbols():
    row = {
        "tradingsymbol": "CCC",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 3,
    }  # the shape in Kite's documentation
    rows = [
        row,
        {**row, "product": "MIS", "quantity": 99},
        {**row, "tradingsymbol": "ZZZ"},
        {**row, "exchange": "BSE"},
        {**row, "quantity": 2},
    ]
    b, _ = account(**{"/portfolio/positions": {"net": rows, "day": []}})
    assert b.day_positions() == {9: 5}
    assert account()[0].day_positions() == {}  # the recorded response of a day with no trades


def test_the_portfolio_never_counts_a_purchase_twice_when_kite_shows_it_in_both_places():
    row = {"tradingsymbol": "BBB", "exchange": "NSE", "product": "CNC", "quantity": 5}
    both = account(
        **{
            "/portfolio/positions": {
                "net": [row, {**row, "tradingsymbol": "CCC", "quantity": 4}],
                "day": [],
            }
        }
    )[0]
    assert both.portfolio() == {
        7: 100,
        8: 15,
        9: 4,
    }  # BBB's 5 are inside its holding of 15; CCC is only in positions


def test_available_cash_is_the_equity_net_balance_and_a_failed_read_is_reported():
    b, kite = account()
    assert b.available_cash() == D("1234.5")
    kite.get_status = 500
    with pytest.raises(BrokerError, match="HTTP 500 reading"):
        b.holdings()
    kite.get_status = 0
    with pytest.raises(BrokerTimeout, match="no answer reading"):
        b.available_cash()

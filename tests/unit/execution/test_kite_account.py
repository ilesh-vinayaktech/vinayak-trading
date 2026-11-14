import json
from decimal import Decimal as D

import pytest

from algo.execution.broker import BrokerError, BrokerTimeout
from algo.execution.kite_account import BASE, KiteAccount, KiteSessionExpired
from tests.support.fake_kite import FakeKite

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "kite_portfolio"


def data(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["data"]


def account(**over):
    kite = FakeKite()
    kite.reads = {
        "/portfolio/holdings": data("holdings"),
        "/portfolio/positions": data("positions"),
        "/user/margins": data("margins"),
        **over,
    }
    return KiteAccount("KEY", "TOKEN", kite), kite


def test_it_reads_holdings_positions_and_cash_and_only_ever_sends_gets():
    a, kite = account(
        **{
            "/portfolio/positions": {
                "net": [
                    {
                        "tradingsymbol": "CCC",
                        "exchange": "NSE",
                        "product": "CNC",
                        "quantity": 3,
                        "average_price": 10.5,
                        "last_price": 11,
                        "pnl": 1.5,
                    }
                ],
                "day": [],
            }
        }
    )
    got = a.read()
    assert got.cash == D("1234.5")
    assert [
        (h.symbol, h.quantity, h.unsettled, h.total, h.average_price) for h in got.holdings
    ] == [("AAA", 100, 0, 100, D("200.5")), ("BBB", 10, 5, 15, D("50.25"))]
    assert [(p.symbol, p.product, p.quantity, p.average_price, p.pnl) for p in got.positions] == [
        ("CCC", "CNC", 3, D("10.5"), D("1.5"))
    ]
    assert [(m, u.removeprefix(BASE)) for m, u, *_ in kite.calls] == [
        ("GET", "/portfolio/holdings"),
        ("GET", "/portfolio/positions"),
        ("GET", "/user/margins"),
    ]
    assert kite.calls[0][2] == {"X-Kite-Version": "3", "Authorization": "token KEY:TOKEN"}


def test_a_refused_session_no_answer_and_an_unreadable_answer_are_told_apart():
    a, kite = account()
    kite.get_status = 403
    with pytest.raises(KiteSessionExpired, match="holdings"):
        a.read()
    kite.get_status = 500
    with pytest.raises(BrokerError, match="HTTP 500 reading holdings"):
        a.read()
    kite.get_status = 0
    with pytest.raises(BrokerTimeout, match="no answer reading holdings"):
        a.read()
    kite.get_status = 200
    kite.reads["/portfolio/holdings"] = None  # a success with nothing in it
    with pytest.raises(BrokerError):
        a.read()
    broken = KiteAccount("KEY", "TOKEN", lambda *_a, **_k: (200, b"<html>"))
    with pytest.raises(BrokerError, match="unreadable"):
        broken.read()

from datetime import UTC, datetime
from decimal import Decimal as D

from algo.core.clock import SimClock
from algo.execution.broker import BrokerError, BrokerTimeout
from algo.execution.kite_account import Account, HoldingRow
from algo.execution.live_reconcile import reconcile_live
from algo.execution.oms import Mismatch, Oms
from algo.risk.engine import RiskEngine
from algo.risk.killswitch import KillSwitch, Mode
from algo.risk.limits import Limits
from algo.risk.model import Book, Day, Market, OrderRequest, Side
from tests.support.fake_broker import FakeBroker

NOW = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)
SYMBOLS = {7: "INFY", 8: "TCS"}


def holding(symbol, qty, t1=0):
    return HoldingRow(symbol, "NSE", qty, t1, D(1), D(1), D(0))


class Reader:
    def __init__(self, holdings=(), error=None):
        self.account, self.error = Account(D(0), list(holdings), []), error

    def read(self):
        if self.error:
            raise self.error
        return self.account


def oms_that_bought(qty=10):
    broker, switch = FakeBroker(), KillSwitch()
    oms = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW))
    o = oms.submit("k", OrderRequest("s1", 7, Side.BUY, qty), Market(ltp=D(100)), Book(), Day())
    oms.on_update(broker.move(o.order_id, "COMPLETE", qty, D(100)))
    return oms, switch


def test_a_broker_that_holds_what_we_bought_and_more_of_the_owners_own_is_clean():
    oms, _ = oms_that_bought(10)
    reader = Reader(
        [holding("INFY", 1000, 10), holding("TCS", 50), holding("OTHER", 5)]
    )  # owner's own shares, and a stock we never mapped
    assert reconcile_live(oms, reader, SYMBOLS) == []


def test_shares_we_bought_that_are_gone_from_the_broker_are_a_mismatch_and_halt_trading():
    oms, switch = oms_that_bought(10)
    found = reconcile_live(oms, Reader([holding("INFY", 4)]), SYMBOLS)
    assert [m.kind for m in found] == ["POSITION_MISMATCH"]
    assert switch.mode("s1") is not Mode.RUNNING and oms.alerts


def test_unsettled_shares_count_as_held():
    oms, _ = oms_that_bought(10)
    assert reconcile_live(oms, Reader([holding("INFY", 6, 4)]), SYMBOLS) == []


def test_an_account_that_cannot_be_read_halts_trading_like_an_unreadable_order_list():
    for err in (BrokerTimeout("no answer"), BrokerError("unreadable")):
        oms, switch = oms_that_bought(10)
        found = reconcile_live(oms, Reader(error=err), SYMBOLS)
        assert [m.kind for m in found] == ["BROKER_UNREACHABLE"]
        assert switch.mode("s1") is not Mode.RUNNING


# ---- found by mutation testing -------------------------------------------------------------------------------------
def test_an_unreadable_account_is_one_unreachable_mismatch_with_the_reason_and_no_order_id():
    oms, _ = oms_that_bought(10)
    found = reconcile_live(oms, Reader(error=BrokerTimeout("no answer")), SYMBOLS)
    assert found == [Mismatch("BROKER_UNREACHABLE", "", "the account could not be read: no answer")]


def test_several_rows_of_one_symbol_add_up_and_a_symbol_the_account_lacks_counts_as_zero():
    oms, _ = oms_that_bought(10)
    two_rows = Reader(
        [holding("INFY", 4, 0), holding("INFY", 3, 3)]
    )  # 7 + 3 (t+1) = 10: exactly what we bought
    assert reconcile_live(oms, two_rows, SYMBOLS) == []
    short = reconcile_live(
        oms, Reader([holding("INFY", 4), holding("INFY", 3)]), SYMBOLS
    )  # 7 held, 10 bought
    assert [m.detail for m in short] == ["instrument 7: we hold 10, the broker 7"]


def test_the_positions_of_two_strategies_in_one_stock_are_added_before_the_comparison():
    broker, switch = FakeBroker(), KillSwitch()
    oms = Oms(broker, RiskEngine(Limits(), switch), SimClock(NOW))
    for strategy, qty in (("s1", 6), ("s2", 4)):
        o = oms.submit(
            "k", OrderRequest(strategy, 7, Side.BUY, qty), Market(ltp=D(100)), Book(), Day()
        )
        oms.on_update(broker.move(o.order_id, "COMPLETE", qty, D(100)))
    assert reconcile_live(oms, Reader([holding("INFY", 10)]), SYMBOLS) == []  # 6 + 4 = 10
    assert [m.detail for m in reconcile_live(oms, Reader([holding("INFY", 9)]), SYMBOLS)] == [
        "instrument 7: we hold 10, the broker 9"
    ]

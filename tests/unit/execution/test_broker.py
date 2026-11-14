from decimal import Decimal as D

from algo.execution.broker import BrokerError, BrokerOrder, BrokerRejected, BrokerTimeout


def test_a_timeout_is_not_a_rejection_and_both_are_broker_errors():
    assert issubclass(BrokerTimeout, BrokerError) and issubclass(BrokerRejected, BrokerError)
    assert not issubclass(BrokerTimeout, BrokerRejected) and not issubclass(
        BrokerRejected, BrokerTimeout
    )


def test_a_broker_order_carries_our_tag():
    o = BrokerOrder("B1", "A123", "PARTIAL", 4, D(100))
    assert (o.client_order_id, o.filled_qty) == ("A123", 4)
    assert BrokerOrder("B2", "A2", "OPEN").filled_qty == 0

"""A scriptable broker for the OMS tests: it remembers every call and can time out before or after taking an order."""

from algo.execution.broker import BrokerOrder, BrokerRejected, BrokerTimeout


class Crash(BaseException):
    """The process dies here: not an error the OMS may catch (BaseException, like a kill)."""


class FakeBroker:
    def __init__(self, script=()):
        self.script = list(
            script
        )  # one behaviour per place_order call: ok | reject | timeout_before | timeout_after
        self.book: dict[str, BrokerOrder] = {}
        self.place_calls = 0
        self.cancel_calls: list[str] = []
        self.cancel_fails = False
        self.list_fails = False

    def place_order(self, req, client_order_id):
        self.place_calls += 1
        behaviour = self.script.pop(0) if self.script else "ok"
        if behaviour == "reject":
            raise BrokerRejected("insufficient margin")
        if behaviour == "crash_before":
            raise Crash  # died before the order left the process
        if behaviour == "timeout_before":
            raise BrokerTimeout("timed out")  # the broker never saw the order
        broker_id = f"B{len(self.book) + 1}"
        self.book[client_order_id] = BrokerOrder(broker_id, client_order_id, "OPEN")
        if behaviour == "crash_after":
            raise Crash  # the broker has it, the process died before it heard
        if behaviour == "timeout_after":
            raise BrokerTimeout("timed out")  # the broker has it, the reply was lost
        return broker_id

    def cancel_order(self, broker_order_id):
        self.cancel_calls.append(broker_order_id)
        if self.cancel_fails:
            raise BrokerTimeout("timed out")

    def orders(self):
        if self.list_fails:
            raise BrokerTimeout("timed out")
        return list(self.book.values())

    def move(self, client_order_id, status, filled_qty=0, avg_price=None):
        old = self.book[client_order_id]
        self.book[client_order_id] = BrokerOrder(
            old.broker_order_id, client_order_id, status, filled_qty, avg_price
        )
        return self.book[client_order_id]

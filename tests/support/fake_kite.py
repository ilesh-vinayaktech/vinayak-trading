"""A stand-in for Kite's order endpoints: the same transport signature as urllib_http, an order book, and scripted failures."""

import json


def ok(data):
    return 200, json.dumps({"status": "success", "data": data}).encode()


def err(status, message, error_type="InputException"):
    return status, json.dumps(
        {"status": "error", "message": message, "error_type": error_type}
    ).encode()


class FakeKite:
    def __init__(self, script=()):
        self.script = list(
            script
        )  # one behaviour per POST: ok | timeout_before | timeout_after | http500 | 429 | 403 | 400
        self.calls = []  # (method, url, headers, data)
        self.book = []  # Kite's order dicts
        self.get_status = 200
        self.delete_status = 200

    def __call__(self, method, url, headers, data=None):
        self.calls.append((method, url, headers, data))
        if method == "POST":
            behaviour = self.script.pop(0) if self.script else "ok"
            if behaviour == "timeout_before":
                return 0, b"timed out"
            if behaviour == "http500":
                return err(500, "internal error", "GeneralException")
            if behaviour == "429":
                return err(429, "too many requests", "NetworkException")
            if behaviour == "403":
                return err(403, "token expired", "TokenException")
            if behaviour == "400":
                return err(400, "Insufficient funds. Required margin is 1,000", "MarginException")
            order_id = str(220000000000 + len(self.book))
            self.book.append(
                {
                    "order_id": order_id,
                    "tag": data.get("tag"),
                    "status": "OPEN",
                    "filled_quantity": 0,
                    "average_price": 0,
                    "status_message": None,
                    "quantity": int(data["quantity"]),
                }
            )
            if behaviour == "timeout_after":
                return 0, b"timed out"  # the exchange has it, the reply was lost
            return ok({"order_id": order_id})
        if method == "DELETE":
            if self.delete_status != 200:
                return (
                    (0, b"timed out")
                    if self.delete_status == 0
                    else err(self.delete_status, "Order cannot be cancelled")
                )
            return ok({"order_id": url.rsplit("/", 1)[1]})
        if method == "GET":
            return (self.get_status, b"x") if self.get_status != 200 else ok(self.book)
        raise AssertionError(method)

    def move(self, order_id, status, filled=0, avg=0, message=None):
        o = next(o for o in self.book if o["order_id"] == order_id)
        o.update(status=status, filled_quantity=filled, average_price=avg, status_message=message)

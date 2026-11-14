# ruff: noqa: E501
"""The Kite Connect order adapter (spec section 11). The only thing in this codebase that can place a real order, so:
  * it will not start without a LiveGate (explicit flag + a LIVE-stage strategy + a valid session, see live_gate.py)
  * an answer that says "not placed" (400, 403, 429) is a BrokerRejected with Kite's reason; NO answer, or a server error, is a
    BrokerTimeout (the order may exist) and is never retried here: the OMS looks the order up by its tag instead
  * every order carries the client_order_id as Kite's `tag`, so an order can always be found again
Product is CNC (delivery) like the cost schedules; market orders are MARKET, priced ones LIMIT; validity DAY. Not exercised against the real
exchange: it is tested against a fake with Kite's response shapes, and real use needs a person to read Kite's current terms first."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from algo.execution.broker import BrokerError, BrokerOrder, BrokerRejected, BrokerTimeout
from algo.execution.live_gate import LiveGate, LiveRefused
from algo.risk.model import OrderRequest

BASE = "https://api.kite.trade"
Http = Callable[..., tuple[int, bytes]]


def _message(body: bytes) -> str:
    try:
        return str(json.loads(body).get("message", ""))
    except (ValueError, AttributeError):
        return body[:120].decode("utf-8", "replace")


class KiteBroker:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        http: Http,
        symbols: Mapping[int, str],
        *,
        gate: LiveGate,
        product: str = "CNC",
        exchange: str = "NSE",
    ) -> None:
        if not gate.open:
            raise LiveRefused("the live gate is not open")
        self._headers = {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"}
        self._http, self.symbols, self.product, self.exchange = http, symbols, product, exchange

    def place_order(self, req: OrderRequest, client_order_id: str) -> str:
        symbol = self.symbols.get(req.instrument_id)
        if symbol is None:
            raise BrokerRejected(f"no Kite symbol for instrument {req.instrument_id}")
        data = {
            "exchange": self.exchange,
            "tradingsymbol": symbol,
            "transaction_type": req.side.value,
            "quantity": str(req.qty),
            "product": self.product,
            "order_type": "MARKET" if req.price is None else "LIMIT",
            "validity": "DAY",
            "tag": client_order_id,
        }
        if req.price is not None:
            data["price"] = str(req.price)
        status, body = self._http("POST", f"{BASE}/orders/regular", self._headers, data)
        if status == 200:
            order_id = json.loads(body).get("data", {}).get("order_id")
            if not order_id:
                raise BrokerTimeout("Kite answered success with no order id: the order may exist")
            return str(order_id)
        if status in (400, 403, 429):  # Kite says it did not take the order
            why = {403: "the Kite session is not valid", 429: "rate limited, not placed"}.get(
                status
            ) or _message(body)
            raise BrokerRejected(why)
        raise BrokerTimeout(f"no usable answer (HTTP {status}): the order may exist")

    def cancel_order(self, broker_order_id: str) -> None:
        status, body = self._http(
            "DELETE", f"{BASE}/orders/regular/{broker_order_id}", self._headers
        )
        if status == 200:
            return
        if status == 0:
            raise BrokerTimeout("no answer to the cancel")
        raise BrokerError(f"cannot be cancelled: {_message(body)}")

    def orders(self) -> list[BrokerOrder]:
        status, body = self._http("GET", f"{BASE}/orders", self._headers)
        if status == 0:
            raise BrokerTimeout("no answer reading the order book")
        if status != 200:
            raise BrokerError(f"HTTP {status} reading the order book")
        return [self._order(o) for o in json.loads(body)["data"]]

    @staticmethod
    def _order(o: Mapping[str, Any]) -> BrokerOrder:
        filled = int(o.get("filled_quantity") or 0)
        kind = str(o["status"])
        status = {"COMPLETE": "COMPLETE", "REJECTED": "REJECTED", "CANCELLED": "CANCELLED"}.get(
            kind, "PARTIAL" if filled else "OPEN"
        )
        avg = Decimal(str(o["average_price"])) if o.get("average_price") else None
        return BrokerOrder(
            str(o["order_id"]),
            o.get("tag") or f"MANUAL-{o['order_id']}",
            status,
            filled,
            avg,
            str(o.get("status_message") or ""),
        )

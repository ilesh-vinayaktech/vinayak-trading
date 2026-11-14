# ruff: noqa: E501
"""The broker seam (spec section 11). Only the OMS holds a Broker. A timeout is NOT a rejection: the broker may or may
not have the order, which is why `BrokerTimeout` is its own type and the OMS never resubmits on it blindly."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from algo.risk.model import OrderRequest

MANUAL_PREFIX = "MANUAL-"  # the id given to an order at the broker that carries none of our tags (placed by hand)


class BrokerError(Exception):
    pass


class BrokerRejected(BrokerError):
    """The broker received the order and refused it: nothing is open at the broker."""


class BrokerTimeout(BrokerError):
    """No answer: the order may or may not exist at the broker."""


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str  # the tag we sent
    status: str  # OPEN | PARTIAL | COMPLETE | CANCELLED | REJECTED | EXPIRED
    filled_qty: int = 0
    avg_price: Decimal | None = None
    reason: str = ""  # why, when the broker says (a rejection)


class Broker(Protocol):
    def place_order(self, req: OrderRequest, client_order_id: str) -> str: ...
    def cancel_order(self, broker_order_id: str) -> None: ...
    def orders(self) -> list[BrokerOrder]: ...

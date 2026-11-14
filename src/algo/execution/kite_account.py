# ruff: noqa: E501
"""A read-only view of a Kite account: holdings, today's positions and cash. It has no way to place, change or cancel an order (it only
ever sends GET), so it needs no live gate and may be used by the portal for any connected person. Everything the account holds is
reported, including shares bought by hand in the Kite app; deciding which of it belongs to the platform is the caller's job.
Shapes follow Kite's responses as recorded on 2026-11-14 (holdings, margins) and its documentation (positions: no trade was open that day)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from algo.execution.broker import BrokerError, BrokerTimeout

BASE = "https://api.kite.trade"
Http = Callable[..., tuple[int, bytes]]


class KiteSessionExpired(BrokerError):
    """Kite refused the token (HTTP 403): the daily login has to be done again."""


@dataclass(frozen=True)
class HoldingRow:
    symbol: str
    exchange: str
    quantity: int  # settled
    unsettled: int  # bought and not settled yet (T+1)
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal

    @property
    def total(self) -> int:
        return self.quantity + self.unsettled


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    exchange: str
    product: str
    quantity: int  # net, signed
    average_price: Decimal
    last_price: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class Account:
    cash: Decimal  # equity cash usable now
    holdings: list[HoldingRow]
    positions: list[PositionRow]


def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))


class KiteAccount:
    def __init__(self, api_key: str, access_token: str, http: Http) -> None:
        self._headers = {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"}
        self._http = http

    def _read(self, path: str, what: str) -> Any:
        status, body = self._http("GET", f"{BASE}{path}", self._headers)
        if status == 0:
            raise BrokerTimeout(f"no answer reading {what}")
        if status == 403:
            raise KiteSessionExpired(f"Kite refused the session reading {what}")
        if status != 200:
            raise BrokerError(f"Kite answered HTTP {status} reading {what}")
        try:
            return json.loads(body)["data"]
        except (ValueError, KeyError, TypeError) as e:
            raise BrokerError(f"unreadable answer reading {what}") from e

    def read(self) -> Account:
        try:
            return self._build()
        except (
            KeyError,
            TypeError,
            ValueError,
            ArithmeticError,
        ) as e:  # a success answer that is not the shape Kite documents
            raise BrokerError("unreadable answer reading the account") from e

    def _build(self) -> Account:
        holdings = [
            HoldingRow(
                h["tradingsymbol"],
                h.get("exchange", "NSE"),
                int(h.get("quantity") or 0),
                int(h.get("t1_quantity") or 0),
                _dec(h.get("average_price")),
                _dec(h.get("last_price")),
                _dec(h.get("pnl")),
            )
            for h in self._read("/portfolio/holdings", "holdings")
        ]
        positions = [
            PositionRow(
                p["tradingsymbol"],
                p.get("exchange", "NSE"),
                p.get("product", ""),
                int(p.get("quantity") or 0),
                _dec(p.get("average_price")),
                _dec(p.get("last_price")),
                _dec(p.get("pnl")),
            )
            for p in self._read("/portfolio/positions", "positions")["net"]
        ]
        cash = _dec(self._read("/user/margins", "margins")["equity"]["net"])
        return Account(cash, holdings, positions)

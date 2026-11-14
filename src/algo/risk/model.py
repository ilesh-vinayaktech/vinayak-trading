# ruff: noqa: E501
"""The data the risk engine looks at. Plain values, no database, no clock: the caller (portfolio and risk service)
fills them in from the ledger and the market, so every check is a pure function of its inputs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


@dataclass(frozen=True)
class OrderRequest:
    strategy_id: str
    instrument_id: int
    side: Side
    qty: int
    price: Decimal | None = (
        None  # limit price; None is a market order, valued at the last traded price
    )
    reduce_only: bool = False  # may only close or shrink the current position


@dataclass(frozen=True)
class Market:
    ltp: Decimal  # last traded price
    adv: int | None = None  # average daily volume in shares
    sector: str | None = None
    tradable: bool = True  # False: expired contract, suspended or halted


@dataclass(frozen=True)
class Book:
    """The portfolio as it stands before the order. Values are rupees; signed where noted."""

    position_qty: int = 0  # this instrument, signed (short < 0)
    instrument_value: Decimal = Decimal(0)  # this instrument, signed
    sector_value: Decimal = Decimal(0)  # this order's sector, signed
    gross_value: Decimal = Decimal(0)  # sum of absolute position values
    net_value: Decimal = Decimal(0)  # sum of signed position values
    margin_available: Decimal = Decimal(0)
    open_orders: int = 0


@dataclass(frozen=True)
class Day:
    """Today's activity for the strategy (or the portfolio) the order belongs to."""

    orders: int = 0
    turnover: Decimal = Decimal(0)
    pnl: Decimal = Decimal(0)  # negative is a loss
    consecutive_failures: int = 0


@dataclass(frozen=True)
class Rejection:
    code: str
    detail: str


@dataclass(frozen=True)
class Decision:
    rejections: tuple[Rejection, ...] = ()

    @property
    def approved(self) -> bool:
        return not self.rejections

    @property
    def codes(self) -> list[str]:
        return [r.code for r in self.rejections]

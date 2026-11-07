"""What the backtest engine asks of a cost model: itemised charges for an order, a fill price with
slippage, and any contract-note-level top-up. Two implementations:

  CostModel      flat basis points - a flagged PLACEHOLDER, kept for tests and quick looks
  ScheduleCosts  effective-dated statutory/broker schedules (config/cost_schedules) + slippage
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from algo.backtest.costs.calculator import (
    ChargeLine,
    Charges,
    compute_charges,
    contract_note_shortfall,
)
from algo.backtest.costs.schedule import ScheduleBook
from algo.backtest.costs.slippage import BPS, SlippageModel, fill_price, slippage_bps


@dataclass(frozen=True)
class Liquidity:
    """What is known about an instrument when an order is placed (all from BEFORE the bar, except
    the bar's own volume, which sets how large the order is relative to the market)."""

    volume: Decimal  # the execution bar's traded volume
    range_bps: Decimal  # recent average (high - low) / close, in bps
    adv_value: Decimal | None  # recent average daily traded value, rupees (None = unknown)


class CostPolicy(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def placeholder(self) -> bool: ...
    @property
    def zero_slippage(self) -> bool: ...
    def charges(self, day: date, side: str, qty: Decimal, price: Decimal) -> Charges: ...
    def fill(
        self, side: str, reference: Decimal, qty: Decimal, liq: Liquidity
    ) -> tuple[Decimal, Decimal]: ...
    def note_shortfall(self, day: date, brokerage_total: Decimal) -> Decimal: ...
    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CostModel:
    name: str
    commission_bps: Decimal
    slippage_bps: Decimal
    placeholder: bool  # True until a versioned cost schedule replaces flat bps

    @property
    def zero_slippage(self) -> bool:
        return self.slippage_bps == 0

    def charges(self, day: date, side: str, qty: Decimal, price: Decimal) -> Charges:
        value = qty * price
        line = ChargeLine(
            "COMMISSION", value * self.commission_bps / BPS, value,
            f"{self.commission_bps} bps of {value}", "NONE", self.name,
        )  # fmt: skip
        return Charges(side, self.name, "1", "placeholder", (line,))

    def fill(
        self, side: str, reference: Decimal, qty: Decimal, liq: Liquidity
    ) -> tuple[Decimal, Decimal]:
        return fill_price(reference, side, self.slippage_bps), self.slippage_bps

    def note_shortfall(self, day: date, brokerage_total: Decimal) -> Decimal:
        return Decimal(0)

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "flat_bps", "name": self.name, "placeholder": self.placeholder,
            "commission_bps": str(self.commission_bps), "slippage_bps": str(self.slippage_bps),
            "zero_slippage": self.zero_slippage,
        }  # fmt: skip


PLACEHOLDER_COSTS = CostModel("flat-bps-placeholder", Decimal(10), Decimal(5), True)


@dataclass(frozen=True)
class ScheduleCosts:
    book: ScheduleBook
    slippage: SlippageModel
    product: str = "DELIVERY"
    name: str = "schedule-costs"
    placeholder: bool = False

    @property
    def zero_slippage(self) -> bool:
        return self.slippage.is_zero

    def charges(self, day: date, side: str, qty: Decimal, price: Decimal) -> Charges:
        return compute_charges(self.book.for_date(day, self.product), side, qty, price)

    def fill(
        self, side: str, reference: Decimal, qty: Decimal, liq: Liquidity
    ) -> tuple[Decimal, Decimal]:
        bps = slippage_bps(
            self.slippage,
            participation=qty / liq.volume,
            range_bps=liq.range_bps,
            adv_value=liq.adv_value,
        )
        return fill_price(reference, side, bps), bps

    def note_shortfall(self, day: date, brokerage_total: Decimal) -> Decimal:
        return contract_note_shortfall(self.book.for_date(day, self.product), brokerage_total)

    def describe(self) -> dict[str, Any]:
        return {
            "kind": "schedule", "name": self.name, "placeholder": self.placeholder,
            "product": self.product, "allowed_statuses": list(self.book.allowed),
            "coverage": [
                [str(a), str(b) if b else None] for a, b in self.book.coverage(self.product)
            ],
            "slippage": {k: str(v) for k, v in vars(self.slippage).items()},
            "zero_slippage": self.zero_slippage,
        }  # fmt: skip

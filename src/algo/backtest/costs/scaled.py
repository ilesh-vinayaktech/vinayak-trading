"""Cost stress: the same policy with every charge and every slippage bp multiplied. A strategy that
only works at 1x costs is not robust; validation re-runs at 2x."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from algo.backtest.costs.calculator import Charges
from algo.backtest.costs.policy import CostPolicy, Liquidity
from algo.backtest.costs.slippage import fill_price


@dataclass(frozen=True)
class ScaledCosts:
    base: CostPolicy
    factor: Decimal

    def __post_init__(self) -> None:
        if self.factor <= 0:
            raise ValueError("cost factor must be positive")

    @property
    def name(self) -> str:
        return f"{self.base.name}x{self.factor}"

    @property
    def placeholder(self) -> bool:
        return self.base.placeholder

    @property
    def zero_slippage(self) -> bool:
        return self.base.zero_slippage

    def charges(self, day: date, side: str, qty: Decimal, price: Decimal) -> Charges:
        c = self.base.charges(day, side, qty, price)
        lines = tuple(replace(ln, amount=ln.amount * self.factor) for ln in c.lines)
        return replace(c, lines=lines)

    def fill(
        self, side: str, reference: Decimal, qty: Decimal, liq: Liquidity
    ) -> tuple[Decimal, Decimal]:
        _, bps = self.base.fill(side, reference, qty, liq)
        bps *= self.factor
        return fill_price(reference, side, bps), bps

    def note_shortfall(self, day: date, brokerage_total: Decimal) -> Decimal:
        return self.base.note_shortfall(day, brokerage_total) * self.factor

    def describe(self) -> dict[str, Any]:
        return {**self.base.describe(), "stress_factor": str(self.factor)}

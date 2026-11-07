"""Slippage is an EXECUTION-MODEL estimate, kept apart from statutory charges and brokerage.
bps = base + participation term + volatility term + illiquidity surcharge, capped at max_bps.
Buys fill above the reference price, sells below. Inputs come only from data known BEFORE the
execution bar (recent ranges / traded value) plus the order's own share of the bar's volume."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

BPS = Decimal(10000)


@dataclass(frozen=True)
class SlippageModel:
    base_bps: Decimal = Decimal(0)
    participation_bps_per_pct: Decimal = Decimal(0)  # bps added per 1% of the bar's volume
    volatility_fraction: Decimal = Decimal(0)  # share of the recent average daily range, in bps
    illiquid_adv_threshold: Decimal | None = None  # average daily traded value (rupees)
    illiquid_extra_bps: Decimal = Decimal(0)
    max_bps: Decimal = Decimal(1000)

    def __post_init__(self) -> None:
        values = (
            self.base_bps, self.participation_bps_per_pct, self.volatility_fraction,
            self.illiquid_extra_bps, self.max_bps,
        )  # fmt: skip
        if any(v < 0 for v in values):
            raise ValueError("slippage parameters cannot be negative")

    @property
    def is_zero(self) -> bool:
        return (
            self.base_bps == 0
            and self.participation_bps_per_pct == 0
            and self.volatility_fraction == 0
            and self.illiquid_extra_bps == 0
        )


def slippage_bps(
    m: SlippageModel, *, participation: Decimal, range_bps: Decimal, adv_value: Decimal | None
) -> Decimal:
    """participation = order qty / bar volume (0..1); range_bps = recent average (high-low)/close
    in bps; adv_value = recent average daily traded value in rupees (None = unknown)."""
    bps = (
        m.base_bps
        + participation * 100 * m.participation_bps_per_pct
        + m.volatility_fraction * range_bps
    )
    if m.illiquid_adv_threshold is not None and (
        adv_value is None or adv_value < m.illiquid_adv_threshold
    ):
        bps += m.illiquid_extra_bps
    return min(bps, m.max_bps)


def fill_price(reference: Decimal, side: str, bps: Decimal) -> Decimal:
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    return reference * (1 + bps / BPS) if side == "BUY" else reference * (1 - bps / BPS)

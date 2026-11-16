# ruff: noqa: E501
"""Risk limits as configuration. Every field is optional: a limit that is not set is not checked, so a limit can be
added, tightened or removed by editing the mapping that loads here, never the code."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import time
from decimal import Decimal
from typing import Any

NULLABLE = frozenset(
    {"max_trade_loss"}
)  # limits that are ON by default: only these can be switched off by writing null


class LimitsError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    allowed: frozenset[int] | None = None  # allow-list of instruments; None = any
    restricted: frozenset[int] = frozenset()  # never tradable, whatever the allow-list says
    max_order_qty: int | None = None
    max_order_value: Decimal | None = None
    max_adv_fraction: Decimal | None = None  # order qty as a share of average daily volume
    fat_finger_band: Decimal | None = (
        None  # limit price may differ from the last price by at most this fraction
    )
    max_instrument_value: Decimal | None = None  # absolute position value after the order
    max_sector_value: Decimal | None = None
    max_gross_value: Decimal | None = None
    max_net_value: Decimal | None = None  # absolute net value after the order
    check_margin: bool = False  # a buy must fit in the margin available
    max_open_orders: int | None = None
    order_rate_per_s: Decimal | None = None  # token bucket refill
    order_burst: int = 1
    trading_hours: tuple[time, time] | None = None  # IST, [open, close]
    max_daily_orders: int | None = None
    max_daily_turnover: Decimal | None = None
    max_daily_loss: Decimal | None = None  # a positive number: the loss at which trading stops
    max_consecutive_failures: int | None = None
    max_drawdown: Decimal | None = None  # fraction of peak equity, e.g. 0.1
    max_trade_loss: Decimal | None = Decimal(
        "0.02"
    )  # per open position: the adverse move from its entry price at which `trade_stops` says exit (owner, 2026-11-15: 2% by default; None switches it off)
    max_data_age_s: Decimal | None = None  # no fresh bar or quote for this long halts the strategy
    min_fill_rate: Decimal | None = None  # post-trade: filled / ordered quantity
    slippage_tolerance: Decimal = Decimal(
        2
    )  # post-trade: flag when realised slippage exceeds this multiple of the model's

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Limits:
        """Build from plain config values (strings for money and times); unknown keys are refused, never ignored."""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise LimitsError(f"unknown limit(s): {', '.join(unknown)}")
        out: dict[str, Any] = {}
        for key, value in raw.items():
            if key in ("allowed", "restricted"):
                out[key] = frozenset(int(v) for v in value)
            elif key == "check_margin":
                out[key] = bool(value)
            elif key == "trading_hours":
                out[key] = (time.fromisoformat(value[0]), time.fromisoformat(value[1]))
            elif value is None and key in NULLABLE:
                out[key] = None  # an explicit null switches a limit that has a default off
            elif key in (
                "max_order_qty",
                "order_burst",
                "max_open_orders",
                "max_daily_orders",
                "max_consecutive_failures",
            ):
                out[key] = int(value)
            else:
                out[key] = Decimal(str(value))
        return cls(**out)

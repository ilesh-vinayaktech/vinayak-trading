"""Timeframe-agnostic bar model. 1d (bhavcopy) and 1m (Kite) share Bar, validity checks, the
versioned loader and the pipeline; only this registry differs. ts = bar-OPEN, UTC."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Freq(StrEnum):
    D1 = "1d"
    M1 = "1m"


@dataclass(frozen=True)
class FreqSpec:
    table: str
    extras: tuple[str, ...]  # provider-specific optional columns on that table


SPECS: Mapping[Freq, FreqSpec] = MappingProxyType(
    {
        Freq.D1: FreqSpec("bar_1d", ("series", "prev_close", "delivery_qty")),
        Freq.M1: FreqSpec("bar_1m", ("oi",)),
    }
)


@dataclass(frozen=True)
class Bar:
    symbol: str  # provider symbol; mapped to instrument_id via instrument_alias
    ts: datetime  # bar-open, tz-aware UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    extra: Mapping[str, Any] = field(default_factory=dict)

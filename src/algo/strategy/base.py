"""Strategy contract. A strategy only decides what it wants to hold (target weights); the engine
owns sizing, costs, risk, execution and accounting. It sees the world only through `Context`."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from algo.strategy.context import Context

Targets = dict[int, Decimal]  # instrument_id -> target weight (fraction of equity, long-only)


class Mode(StrEnum):
    RESEARCH = "research"  # may use provisional corporate-action estimates (always reported)
    STRICT = "strict"  # verified data only; the only mode that can support promotion


class StrategyParams(BaseModel):
    """Base for a strategy's validated, immutable parameter schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True)
class Requirements:
    lookback_days: int = 365  # calendar days of history the strategy reads
    adjust: str = "split"  # none | split | total_return


class Strategy(ABC):
    id: str
    version: str
    Params: type[StrategyParams]

    def __init__(self, params: StrategyParams) -> None:
        self.params = params

    @property
    def params_hash(self) -> str:
        return hashlib.sha256(self.params.model_dump_json().encode()).hexdigest()[:16]

    @abstractmethod
    def universe(self, ctx: Context) -> list[int]: ...

    def requirements(self) -> Requirements:
        return Requirements()

    def on_start(self, ctx: Context) -> None:  # noqa: B027 - optional hook
        pass

    @abstractmethod
    def on_schedule(self, ctx: Context) -> Targets | None:
        """Called after each session closes. None = keep the previous targets."""

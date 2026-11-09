"""The only door from a strategy to the outside world. Strategies get no database handle, no broker
handle and no clock of their own. History is bounded by ctx.now(): a daily bar is visible only
after it has closed and been published, and only corporate actions known by then are applied."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from algo.core.clock import Clock
from algo.data.reader import AdjBar, Loaded, UnadjustableError


@dataclass(frozen=True)
class PortfolioView:
    """Read-only snapshot."""

    cash: Decimal
    positions: Mapping[int, Decimal]
    equity: Decimal

    @staticmethod
    def of(cash: Decimal, positions: Mapping[int, Decimal], equity: Decimal) -> PortfolioView:
        held = {k: v for k, v in positions.items() if v != 0}
        return PortfolioView(cash, MappingProxyType(held), equity)


class DataAccess:
    def __init__(self, loaded: Mapping[int, Loaded], clock: Clock, adjust: str) -> None:
        self._loaded, self._clock, self._adjust = loaded, clock, adjust
        self.withheld: dict[int, str] = {}  # strict: id -> why its window could not be served

    def history(
        self, instrument_ids: Sequence[int], lookback_days: int, *, adjusted: bool = True
    ) -> dict[int, list[AdjBar]]:
        """Bars up to ctx.now() for each instrument, oldest first. Unknown ids are absent. In strict
        mode a name whose requested window crosses an unresolved corporate action already known by
        now is WITHHELD (absent, reason in `withheld`): it is eligible again once the window no
        longer reaches back across that ex-date."""
        now = self._clock.now()
        start = (now - timedelta(days=lookback_days)).date()
        mode = self._adjust if adjusted else "none"
        out: dict[int, list[AdjBar]] = {}
        for i in instrument_ids:
            if i not in self._loaded:
                continue
            try:
                out[i] = self._loaded[i].history(start, now.date(), adjust=mode, as_of=now).bars
            except UnadjustableError as e:
                self.withheld[i] = str(e)
        return out


class Context:
    def __init__(self, clock: Clock, data: DataAccess, portfolio: PortfolioView, mode: str) -> None:
        self._clock, self.data, self.portfolio, self.mode = clock, data, portfolio, mode

    def now(self) -> datetime:
        return self._clock.now()

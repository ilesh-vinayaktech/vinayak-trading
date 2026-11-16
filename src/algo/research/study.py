# ruff: noqa: E501
"""A backtest study: everything the owner configures for an official backtest, checked before it can be registered.

Every choice is the owner's (strategy and its parameter grid, which stocks, the period, the holdout, capital, costs and the
pass/fail thresholds), but each one is fixed the moment the study is registered: changing a setting after seeing a result
is what turns a backtest into curve fitting, so a change means a new study and the trial count goes up.
What is refused here, with the reason: a strategy or parameter value the strategy itself does not accept, a grid so large
that the overfitting correction would swamp any result, a holdout outside 5-50% of the study, an end date in the future, and
a start before October 2019 unless the owner explicitly accepts the survivorship bias (before then our data only holds
stocks still listed today)."""

from __future__ import annotations

import itertools
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from algo.data.benchmark import DEFAULT_BENCHMARK
from algo.strategies.registry import STRATEGIES
from algo.strategies.screener import ScreenSpec

MAX_TRIALS = 64
SURVIVORSHIP_SAFE_FROM = date(2019, 10, 1)  # NSE bhavcopy (which keeps delisted stocks) starts here
SEGMENT_LISTS_FROM = date(
    2018, 8, 1
)  # the first AMFI market-cap list (Jun 2018) is relied on from here
HOLDOUT_SHARE = (0.05, 0.50)
THRESHOLDS_FILE = Path(__file__).resolve().parents[3] / "config" / "validation_thresholds.json"
Segment = Literal["large", "mid", "small", "micro"]


class StudyError(ValueError):
    pass


class UniverseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[Segment] = Field(min_length=1)
    # AMFI's first list is relied on from 2018-08-01; before it, rank by traded value as a stand-in, or leave those days out
    before_segment_lists: Literal["traded_value_rank", "skip"] = "traded_value_rank"
    min_history_sessions: int = Field(default=252, ge=0, le=2000)


class SlippageSpec(BaseModel):
    """What an order costs beyond charges: base bps, bps per 1% of the day's volume taken, and a share of the day's range."""

    model_config = ConfigDict(extra="forbid")
    base_bps: Decimal = Field(default=Decimal(5), ge=0, le=1000)
    participation_bps_per_pct: Decimal = Field(default=Decimal(5), ge=0, le=1000)
    volatility_fraction: Decimal = Field(default=Decimal(0), ge=0, le=1)


class StudySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    hypothesis: str = Field(min_length=20, max_length=4000)
    strategy_id: str = Field(max_length=60)
    grid: dict[str, list[int | float]]
    screen: ScreenSpec | None = (
        None  # the rules of a screener strategy (strategy_id 'screener'), locked with the study
    )
    definition: dict[str, Any] | None = (
        None  # the strategy definition of a 'dsl' study (algo.factory.dsl), locked with the study
    )
    universe: UniverseSpec
    timeframe: Literal["1D"] = (
        "1D"  # the engine decides on daily bars; intraday arrives with intraday strategies
    )
    start: date
    end: date
    holdout_start: date
    capital: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    capacity_multiple: Decimal = Field(default=Decimal(3), ge=1, le=10)
    broker: str = Field(min_length=1, max_length=40)
    product: Literal["DELIVERY"] = "DELIVERY"
    slippage: SlippageSpec = Field(default_factory=SlippageSpec)
    # rupees per order; off by default, which is how studies registered before these existed ran
    min_order_value: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    max_order_value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    benchmark: str = Field(
        default=DEFAULT_BENCHMARK, min_length=1, max_length=120
    )  # a total-return index, by name
    thresholds: dict[str, Decimal]
    accept_survivorship_bias: bool = False
    # days after a filing is broadcast before a screener may use it (0 = from the broadcast); part of the locked study document
    filing_lag_days: int = Field(default=0, ge=0, le=365)
    # the research family this study's trials count toward (registration refuses a study without one)
    family_id: int | None = None

    @model_validator(mode="after")
    def _order_sizes_agree(self) -> StudySpec:
        if self.max_order_value is not None and self.max_order_value < self.min_order_value:
            raise ValueError("the maximum order value cannot be below the minimum")
        return self


def default_thresholds() -> dict[str, str]:
    """The provisional long-only thresholds (config/validation_thresholds.json), as decimal strings."""
    return {k: str(v) for k, v in json.loads(THRESHOLDS_FILE.read_text())["long_only"].items()}


def _check_grid(s: StudySpec, max_trials: int) -> None:
    if s.strategy_id not in STRATEGIES:
        raise StudyError(f"unknown strategy {s.strategy_id!r}")
    if (s.strategy_id == "screener") != (s.screen is not None):
        raise StudyError("a screener study needs its screen, and no other strategy takes one")
    if (s.strategy_id == "dsl") != (s.definition is not None):
        raise StudyError("a dsl study needs its definition, and no other strategy takes one")
    if s.screen is not None and (why := s.screen.problem()):
        raise StudyError(why)
    params = STRATEGIES[s.strategy_id][1]
    if not s.grid:
        raise StudyError("the grid needs at least one parameter")
    for name, values in s.grid.items():
        if name not in params.model_fields:
            raise StudyError(f"{s.strategy_id} has no parameter {name!r}")
        if not values:
            raise StudyError(f"{name} needs at least one value")
        if len(set(values)) != len(values):
            raise StudyError(f"{name} repeats a value")
        for v in values:
            try:
                params.model_validate({name: v})
            except ValidationError as e:
                raise StudyError(f"{name}={v} is not allowed by {s.strategy_id}") from e
    need = max(
        getattr(STRATEGIES[s.strategy_id][0], "required_history", lambda _: 0)(c)
        for c in combinations(s)
    )
    if s.universe.min_history_sessions < need:
        raise StudyError(
            f"stocks need at least {need} sessions of history for this strategy's longest lookback; the study asks for {s.universe.min_history_sessions}"
        )
    n = len(combinations(s))
    if n > max_trials:
        raise StudyError(
            f"{n} trials is more than {max_trials}: every combination counts against the strategy"
        )


def check(
    s: StudySpec, *, today: date, max_trials: int = MAX_TRIALS, development_end: date | None = None
) -> None:
    """Refuse a study that cannot be honoured, with the reason. `development_end` is the research lock's last development day: a
    study may not reach past it (the global holdout begins after it)."""
    if development_end is not None and s.end > development_end:
        raise StudyError(
            f"the study ends {s.end}, inside the global research holdout (development ends {development_end}): register it with an end on or before {development_end}"
        )
    _check_grid(s, max_trials)
    if set(s.thresholds) != set(default_thresholds()):
        raise StudyError(
            f"thresholds must be exactly these twelve: {', '.join(sorted(default_thresholds()))}"
        )
    if s.holdout_start <= s.start:
        raise StudyError("the holdout must start after the study starts")
    if s.holdout_start > s.end:
        raise StudyError("the holdout must start on or before the study's end")
    if s.end > today:
        raise StudyError(f"the study ends {s.end}, in the future")
    share = (s.end - s.holdout_start).days / (s.end - s.start).days
    if not HOLDOUT_SHARE[0] <= share <= HOLDOUT_SHARE[1]:
        raise StudyError(
            f"the holdout is {round(share * 100)}% of the study; keep it between 5% and 50% (the spec suggests 20-30%)"
        )
    if s.start < SURVIVORSHIP_SAFE_FROM and not s.accept_survivorship_bias:
        raise StudyError(
            f"before {SURVIVORSHIP_SAFE_FROM} our data only holds stocks still listed today (survivorship bias): "
            "start later, or accept the bias explicitly"
        )


def combinations(s: StudySpec) -> list[dict[str, Any]]:
    """Every parameter combination of the grid, in a fixed order (names, then values, ascending)."""
    names = sorted(s.grid)
    return [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(sorted(s.grid[n]) for n in names))
    ]

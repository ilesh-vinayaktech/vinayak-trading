# ruff: noqa: E501
"""The strategy definition language (plan.md section 7.2): a typed, validated, hashable description of a long-only daily strategy.

Callers: algo.factory.interpreter (runs it), algo.factory.registry (stores it, immutable) and tests/unit/factory/test_dsl.py.
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".

Nothing in a definition is code. It names features that already exist in the feature registry, compares them with numbers, ranks the candidates, and
sizes the positions; the interpreter turns that into target weights deterministically. A definition that names a feature the registry does not have,
compares with something that is not a finite number, or asks for something outside the allowed shapes is refused when it is parsed, not when it runs.

Version 1 of the language is deliberately small: price and volume features only, long-only, daily decisions. Stop-loss, holding periods, sector or
fundamental features and execution timing are not expressible yet, and saying so is better than accepting words the engine would ignore."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from algo.features import registry as feature_registry

Operator = Literal[">", ">=", "<", "<=", "==", "!=", "TOP_PERCENT", "BOTTOM_PERCENT"]
PERCENT_OPS = frozenset(
    {"TOP_PERCENT", "BOTTOM_PERCENT"}
)  # cross-sectional: 'in the strongest / weakest value% of the stocks that have data that day', so no threshold comes from the data
VOLATILITY_FEATURE = "vol_20d"  # what INVERSE_VOLATILITY sizing divides by
CHAINED = frozenset(
    {"atr_14d", "atr_pct_14d", "rsi_14d"}
)  # Wilder smoothing never forgets its start: their value depends on all history, not a window, so a definition cannot use them yet
FILINGS_FEATURES = frozenset(
    n for n, d in feature_registry.DEFINITIONS.items() if d.needs_filings
)  # fundamental features read the company's filings, which the interpreter does not have: a definition cannot use them yet


def _number(v: Any) -> Decimal:
    """Accept an int, a float or a numeric string; refuse a boolean, text, NaN and infinity. Spelling does not matter: 0.050 and 0.05 are one number."""
    if isinstance(v, bool):
        raise ValueError("a boolean is not a number")
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError("a threshold must be a finite number")
    try:
        d = Decimal(str(v))
    except Exception as e:
        raise ValueError(f"{v!r} is not a number") from e
    if not d.is_finite():
        raise ValueError("a threshold must be a finite number")
    return d.normalize() if d != 0 else Decimal(0)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Condition(_Frozen):
    feature: str
    op: Operator
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def _is_number(cls, v: Any) -> Decimal:
        return _number(v)

    @field_serializer("value")
    def _plain(self, v: Decimal) -> str:
        return format(v, "f")

    @model_validator(mode="after")
    def _a_share_is_a_share(self) -> Self:
        if self.op in PERCENT_OPS and not 0 < self.value <= 100:
            raise ValueError(
                f"{self.op} takes a share between 0 and 100 (above 0, up to 100), not {self.value}"
            )
        return self


class Group(_Frozen):
    all: list[Condition] | None = None  # every one must hold
    any: list[Condition] | None = None  # at least one must hold

    @model_validator(mode="after")
    def _exactly_one_nonempty(self) -> Self:
        given = [g for g in (self.all, self.any) if g is not None]
        if len(given) != 1 or not given[0]:
            raise ValueError("give exactly one of 'all' or 'any', with at least one condition")
        return self

    def conditions(self) -> list[Condition]:
        return list(self.all if self.all is not None else self.any or [])

    def mode(self) -> Literal["all", "any"]:
        return "all" if self.all is not None else "any"


class Ranking(_Frozen):
    """When more stocks qualify than there are free slots, the ones with the best value of this feature are taken first (ties: lower instrument id)."""

    feature: str
    order: Literal["ASC", "DESC"] = "DESC"


class Position(_Frozen):
    max_positions: int = Field(ge=1, le=50)
    sizing: Literal["EQUAL_WEIGHT", "INVERSE_VOLATILITY"] = "EQUAL_WEIGHT"


class Risk(_Frozen):
    max_position_percent: Decimal = Field(gt=0, le=100)

    @field_validator("max_position_percent", mode="before")
    @classmethod
    def _is_number(cls, v: Any) -> Decimal:
        return _number(v)

    @field_serializer("max_position_percent")
    def _plain(self, v: Decimal) -> str:
        return format(v, "f")


class StrategyDef(_Frozen):
    strategy_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,39}$")
    version: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)
    universe: Literal[
        "MEMBERS"
    ]  # the members of the index the runner supplies: the definition does not choose the universe
    timeframe: Literal["DAILY"]
    entry: Group
    exit: Group
    ranking: Ranking
    position: Position
    risk: Risk
    rebalance: Literal["DAILY", "WEEKLY", "MONTHLY"] = "DAILY"

    @model_validator(mode="after")
    def _features_exist(self) -> Self:
        known = set(feature_registry.DEFINITIONS) - CHAINED - FILINGS_FEATURES
        used = {c.feature for c in self.entry.conditions() + self.exit.conditions()} | {
            self.ranking.feature
        }
        unknown = sorted(used - known)
        if unknown:
            raise ValueError(
                f"unknown feature(s) {', '.join(unknown)}; the registered ones are {', '.join(sorted(known))}"
            )
        return self

    def required_features(self) -> set[str]:
        used = {c.feature for c in self.entry.conditions() + self.exit.conditions()} | {
            self.ranking.feature
        }
        if self.position.sizing == "INVERSE_VOLATILITY":
            used.add(VOLATILITY_FEATURE)
        return used

    def warmup_bars(self) -> int:
        """Sessions of history a stock needs before every feature this definition reads has a value."""
        return max(
            int(feature_registry.DEFINITIONS[n].manifest["warmup_bars"])
            for n in self.required_features()
        )

    def position_cap(self) -> float:
        return float(self.risk.max_position_percent) / 100

    def equal_share(self) -> float:
        return 1 / self.position.max_positions

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def parse(text: str) -> StrategyDef:
    """A definition from JSON text. (The plan's examples are YAML; JSON carries the same structure without adding a dependency.)"""
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("a strategy definition is one JSON object")
    return StrategyDef.model_validate(raw)

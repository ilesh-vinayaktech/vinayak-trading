# ruff: noqa: E501
"""A registered strategy definition run through the study machinery (experiments, walk-forward, cost stress, holdout).

Callers: algo.strategies.registry (STRATEGIES["dsl"]), algo.research.study_runner.build and tests/unit/strategies/test_dsl_study.py.
Nothing similar exists: the study grid varies StrategyParams of a coded strategy, a definition has none (algo.factory.interpreter.NoParams).
User's instruction: "Experiments and validation: the experiment runner exists, but nothing links it to the validation gates".

The study locks the whole definition (StudySpec.definition); the grid may only vary its numeric knobs, each counted as a trial. A knob left out keeps the definition's own value."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from algo.factory.dsl import PERCENT_OPS, StrategyDef
from algo.factory.interpreter import DslStrategy
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategy.base import Requirements, Strategy, StrategyParams, Targets
from algo.strategy.context import Context


class DslParams(StrategyParams):
    entry_share: int | None = Field(default=None, ge=1, le=100)
    exit_share: int | None = Field(default=None, ge=1, le=100)
    max_positions: int | None = Field(default=None, ge=1, le=50)


def _shares(raw: dict[str, Any], key: str, share: int) -> None:
    hit = False
    for c in raw[key].get("all", raw[key].get("any", [])):
        if c["op"] in PERCENT_OPS:
            c["value"], hit = share, True
    if not hit:
        raise ValueError(
            f"{key}_share given but the definition's {key} has no TOP_PERCENT / BOTTOM_PERCENT condition"
        )


def apply(defn: StrategyDef, p: DslParams) -> StrategyDef:
    raw = defn.canonical()
    if p.entry_share is not None:
        _shares(raw, "entry", p.entry_share)
    if p.exit_share is not None:
        _shares(raw, "exit", p.exit_share)
    if p.max_positions is not None:
        raw["position"]["max_positions"] = p.max_positions
    return StrategyDef.model_validate(raw)


class DslStudyStrategy(Strategy):
    Params = DslParams

    def __init__(
        self, params: DslParams, membership: IntervalMembership, definition: dict[str, Any]
    ) -> None:
        super().__init__(params)
        self.inner = DslStrategy(apply(StrategyDef.model_validate(definition), params), membership)
        self.id, self.version = self.inner.id, self.inner.version

    @property
    def params_hash(self) -> str:
        return self.inner.params_hash

    def universe(self, ctx: Context) -> list[int]:
        return self.inner.universe(ctx)

    def requirements(self) -> Requirements:
        return self.inner.requirements()

    def on_schedule(self, ctx: Context) -> Targets | None:
        return self.inner.on_schedule(ctx)

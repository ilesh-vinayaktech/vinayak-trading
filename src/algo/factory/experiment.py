# ruff: noqa: E501
"""Experiments on a strategy definition (plan.md section 8): expand a parameter grid into variants, and compare the results with the number of tries accounted for.

Callers: tests/unit/factory/test_experiment.py and algo.factory.lab (which runs the variants and stores the trials).
User's instruction: "do as much as you can do yourself, keep taking things one by one from @TODO.md and @plan.md ... keep things finishing with test".

Pure: no database, no clock, no backtest. What this module insists on:
  * A grid axis is a path into the definition ('entry.all.0.value', 'position.max_positions') naming one existing scalar. The identity of the strategy
    (id, version, description) cannot be varied: an experiment is not a new version.
  * Every combination is a TRIAL, including the ones that turn out to be invalid definitions (they are reported with their reason, not dropped). A grid over
    the limit is refused, never silently truncated, because the number of trials is what the multiple-testing correction needs to be honest.
  * Comparison ranks by Sharpe and then asks what luck alone would have produced from this many tries (the expected best Sharpe, from the spread of the
    trials' own Sharpes) and reports the deflated Sharpe: the probability the result is real after that many attempts."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from algo.backtest.validation import stats
from algo.factory.dsl import StrategyDef

IDENTITY = frozenset({"version", "strategy_id", "description"})
TRADING_DAYS = 252


class ExperimentError(Exception):
    pass


@dataclass(frozen=True)
class Variant:
    overrides: dict[str, Any]
    defn: StrategyDef
    index: int = 0  # the combination's position in the grid, so a skipped one keeps its place


@dataclass(frozen=True)
class Skipped:
    overrides: dict[str, Any]
    reason: str
    index: int = 0


def _set(tree: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if parts[0] in IDENTITY:
        raise ExperimentError(
            f"{parts[0]!r} is part of the strategy's identity and cannot be varied: an experiment is not a new version"
        )
    node: Any = tree
    for step in parts[:-1]:
        node = _child(node, step, path)
    last = parts[-1]
    if isinstance(node, list):  # lists in a definition hold groups of conditions, never bare values
        if not (last.isdigit() and int(last) < len(node)):
            raise ExperimentError(f"no such field {path!r}")
        raise ExperimentError(
            f"{path!r} is not a field you can vary: it is a whole group, name one value inside it"
        )
    if last not in node:
        raise ExperimentError(f"no such field {path!r}")
    if isinstance(node[last], (dict, list)):
        raise ExperimentError(
            f"{path!r} is not a field you can vary: it is a whole group, name one value inside it"
        )
    node[last] = value


def _child(node: Any, step: str, path: str) -> Any:
    if isinstance(node, list):
        if not (step.isdigit() and int(step) < len(node)):
            raise ExperimentError(f"no such field {path!r}")
        return node[int(step)]
    if isinstance(node, dict) and step in node:
        return node[step]
    raise ExperimentError(f"no such field {path!r}")


def variants(
    base: StrategyDef, grid: Mapping[str, Sequence[Any]], max_trials: int = 64
) -> tuple[list[Variant], list[Skipped]]:
    if not grid or any(len(v) == 0 for v in grid.values()):
        raise ExperimentError("nothing to vary: give at least one path with at least one value")
    keys = sorted(grid)
    total = math.prod(len(grid[k]) for k in keys)
    if total > max_trials:
        raise ExperimentError(
            f"the grid makes {total} trials: more than {max_trials} combinations are not run (narrow the grid)"
        )
    ok: list[Variant] = []
    skipped: list[Skipped] = []
    for index, combo in enumerate(itertools.product(*[grid[k] for k in keys])):
        overrides = dict(zip(keys, combo, strict=True))
        tree = base.canonical()  # a fresh dict every call, so editing it never touches the base
        for path, value in overrides.items():
            _set(tree, path, value)
        try:
            ok.append(Variant(overrides, StrategyDef.model_validate(tree), index))
        except ValidationError as e:
            skipped.append(
                Skipped(
                    overrides,
                    "; ".join(
                        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                        for err in e.errors()
                    ),
                    index,
                )
            )
    return ok, skipped


def trial_count(ok: Sequence[Variant], skipped: Sequence[Skipped]) -> int:
    return len(ok) + len(skipped)


@dataclass(frozen=True)
class TrialResult:
    overrides: dict[str, Any]
    definition_sha256: str
    metrics: dict[str, Any]
    result_hash: str
    returns: list[float]  # daily simple returns of the equity curve


@dataclass(frozen=True)
class Ranked:
    overrides: dict[str, Any]
    definition_sha256: str
    metrics: dict[str, Any]
    result_hash: str
    sharpe: float | None  # per period (a day)
    annualised_sharpe: float | None
    deflated_sharpe: float | None  # P(the true Sharpe beats what luck gives after this many trials)


@dataclass(frozen=True)
class Comparison:
    n_trials: int
    sr_variance: float  # spread of the trials' own per-period Sharpes
    expected_max_sharpe: float  # the best per-period Sharpe luck alone would be expected to produce from n_trials tries
    ranked: list[Ranked]

    @property
    def best(self) -> Ranked:
        return self.ranked[0]


def compare(trials: Sequence[TrialResult], attempts: int | None = None) -> Comparison:
    """`attempts` is how many combinations were TRIED (completed, skipped and failed): luck is judged against all of them, not only the ones that finished."""
    if not trials:
        raise ExperimentError("no trials to compare")
    if attempts is not None and attempts < len(trials):
        raise ExperimentError("attempts cannot be fewer than the trials that finished")
    sharpes = [stats.sharpe_per_period(t.returns) for t in trials]
    defined = [s for s in sharpes if s is not None]
    mean = sum(defined) / len(defined) if defined else 0.0
    variance = (
        sum((s - mean) ** 2 for s in defined) / (len(defined) - 1) if len(defined) > 1 else 0.0
    )
    n = attempts if attempts is not None else len(trials)
    rows = [
        Ranked(
            t.overrides,
            t.definition_sha256,
            t.metrics,
            t.result_hash,
            s,
            None if s is None else s * math.sqrt(TRADING_DAYS),
            stats.deflated_sharpe(t.returns, n, variance),
        )  # fmt: skip
        for t, s in zip(trials, sharpes, strict=True)
    ]
    rows.sort(key=lambda r: (r.sharpe is None, 0.0 if r.sharpe is None else -r.sharpe))
    return Comparison(n, variance, stats.expected_max_sharpe(n, variance), rows)

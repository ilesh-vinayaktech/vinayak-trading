# ruff: noqa: E501
"""Strategy degradation detection (plan.md sections 11.2 and 16): is a strategy's recent live (paper) behaviour consistent with what it did in development?

Callers: tests/unit/learning/test_degradation.py and the health-check job. User's instruction: "do as much as you can do yourself, keep taking things one by
one from @TODO.md and @plan.md ... keep things finishing with test". Pure: it is handed two lists of daily returns and returns a verdict with its evidence.

Two independent checks, either of which can degrade a strategy:
  * Mean return. z = (live mean - reference mean) / (reference standard deviation / sqrt(live days)): how many standard errors the recent average sits below
    what development said to expect. At or below `degraded_z` the strategy is DEGRADED, at or below `watch_z` it is on WATCH. (It treats days as independent, which
    flatters a strategy with trending returns; the thresholds are deliberately a little strict for that reason.)
  * Drawdown. A recent worst peak-to-trough fall more than `drawdown_multiple` times the development drawdown is DEGRADED whatever the mean says.
Too little evidence is INSUFFICIENT, never OK: fewer than `min_days` live days, a reference too short to compare with, or a reference with no variation.
Only the most recent `window` live days are judged, so an old bad patch that has since passed does not condemn a strategy forever, and an old good patch does
not hide a new one. Nothing here acts on the verdict: a person or a later gate decides what DEGRADED means for a strategy."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from algo.backtest.validation import stats


@dataclass(frozen=True)
class Thresholds:
    min_days: int = 20  # live days needed before anything is judged
    min_reference_days: int = 60
    watch_z: float = -1.64  # about the 5% one-sided level
    degraded_z: float = -2.33  # about the 1% one-sided level
    drawdown_multiple: float = 1.5  # the spec's 'no worse than 1.5x' rule, applied to the strategy's own development drawdown

    def validate(self) -> None:
        if not (self.degraded_z < self.watch_z < 0):
            raise ValueError("thresholds need degraded_z < watch_z < 0")
        if self.min_days < 5 or self.min_reference_days < 5:
            raise ValueError("min_days and min_reference_days must be at least 5")
        if self.drawdown_multiple < 1:
            raise ValueError("drawdown_multiple must be at least 1")


@dataclass(frozen=True)
class Health:
    status: str  # OK | WATCH | DEGRADED | INSUFFICIENT
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def drawdown(returns: Sequence[float]) -> float:
    """Worst peak-to-trough fall of the compounded curve as a negative fraction (0.0 = none)."""
    equity = peak = 1.0
    worst = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1)
    return worst


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: Sequence[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def assess(
    reference: Sequence[float],
    live: Sequence[float],
    *,
    window: int = 60,
    thresholds: Thresholds | None = None,
) -> Health:
    thresholds = thresholds or Thresholds()
    thresholds.validate()
    recent = list(live[-window:])
    if len(reference) < thresholds.min_reference_days:
        return Health(
            "INSUFFICIENT",
            [
                f"the reference has {len(reference)} days: at least {thresholds.min_reference_days} are needed to compare against"
            ],
        )
    ref_std = _std(reference)
    if ref_std == 0:
        return Health(
            "INSUFFICIENT",
            ["the reference has no variation, so a live result cannot be compared with it"],
        )
    if len(recent) < thresholds.min_days:
        return Health(
            "INSUFFICIENT",
            [f"only {len(recent)} live days: at least {thresholds.min_days} are needed to judge"],
        )
    ref_mean, live_mean = _mean(reference), _mean(recent)
    z = (live_mean - ref_mean) / (ref_std / math.sqrt(len(recent)))
    ref_dd, live_dd = drawdown(reference), drawdown(recent)
    evidence: dict[str, Any] = {
        "live_days": len(recent), "ref_days": len(reference), "live_mean": live_mean, "ref_mean": ref_mean, "ref_std": ref_std, "z": z,
        "live_drawdown": live_dd, "ref_drawdown": ref_dd,
        "live_sharpe": stats.sharpe_per_period(recent), "ref_sharpe": stats.sharpe_per_period(reference),
    }  # fmt: skip
    reasons: list[str] = []
    status = "OK"
    if z <= thresholds.degraded_z:
        status = "DEGRADED"
        reasons.append(
            f"mean return {live_mean:.4%} a day is {abs(z):.2f} standard errors below the reference's {ref_mean:.4%}"
        )
    elif z <= thresholds.watch_z:
        status = "WATCH"
        reasons.append(
            f"mean return {live_mean:.4%} a day is {abs(z):.2f} standard errors below the reference's {ref_mean:.4%}"
        )
    if ref_dd < 0 and live_dd < thresholds.drawdown_multiple * ref_dd:
        status = "DEGRADED"
        reasons.append(
            f"recent drawdown {live_dd:.1%} is deeper than {thresholds.drawdown_multiple}x the development drawdown of {ref_dd:.1%}"
        )
    return Health(status, reasons, evidence)

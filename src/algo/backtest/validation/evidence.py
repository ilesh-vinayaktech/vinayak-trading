"""Assemble the gate `Evidence` from the raw series of a validation run. Pure: it only combines the
existing statistics; anything not supplied stays None, which FAILS its gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from algo.backtest.validation.gates import Evidence
from algo.backtest.validation.robustness import concentration, plateau
from algo.backtest.validation.stats import (
    annualised_sharpe,
    deflated_sharpe,
    max_drawdown,
    pbo_cscv,
    stdev,
)


@dataclass(frozen=True)
class Inputs:
    oos_returns: Sequence[float]  # walk-forward out-of-sample, net of costs, in time order
    window_returns: Sequence[float] = ()  # total return of each walk-forward window
    regime_labels: Sequence[str] = ()  # regime label of each OOS day (any labelling, declared)
    benchmark_returns: Sequence[float] = ()  # SAME dates as oos_returns
    n_trials: int = 1  # from the registry
    trial_sharpes: Sequence[float] = ()  # per-period Sharpe of each registered trial
    trial_returns: Sequence[Sequence[float]] = ()  # return series of each trial (for PBO)
    base_sharpe: float | None = None  # annualised Sharpe of the chosen parameters
    neighbour_sharpes: Sequence[float | None] = ()  # annualised, at the +/-20% settings
    plateau_tolerance: float = 0.3
    returns_2x_costs: Sequence[float] = ()
    returns_3x_capital: Sequence[float] = ()
    by_instrument: Mapping[str, float] = field(default_factory=dict)  # P&L contribution
    by_month: Mapping[str, float] = field(default_factory=dict)
    by_trade: Mapping[str, float] = field(default_factory=dict)
    pbo_blocks: int = 8


def assemble(i: Inputs) -> Evidence:
    oos = list(i.oos_returns)
    bench = list(i.benchmark_returns)
    paired = len(bench) == len(oos) and bool(oos)  # a benchmark on other dates is no benchmark
    sr_var = stdev(list(i.trial_sharpes)) ** 2 if len(i.trial_sharpes) >= 2 else 0.0
    gains = [w for w in i.window_returns if w > 0]
    return Evidence(
        oos_sharpe=annualised_sharpe(oos),
        dsr=deflated_sharpe(oos, max(i.n_trials, 1), sr_var),
        pbo=pbo_cscv(list(i.trial_returns), i.pbo_blocks).pbo
        if len(i.trial_returns) >= 2
        else None,
        max_drawdown=max_drawdown(oos) if oos else None,
        benchmark_max_drawdown=max_drawdown(bench) if paired else None,
        benchmark_sharpe=annualised_sharpe(bench) if paired else None,
        plateau_drop=(
            plateau(i.base_sharpe, list(i.neighbour_sharpes), i.plateau_tolerance).worst_drop
            if i.base_sharpe is not None and i.neighbour_sharpes
            else None
        ),
        sharpe_2x_costs=annualised_sharpe(list(i.returns_2x_costs)),
        sharpe_3x_capital=annualised_sharpe(list(i.returns_3x_capital)),
        top3_instrument=concentration(i.by_instrument) if i.by_instrument else None,
        top3_month=concentration(i.by_month) if i.by_month else None,
        top3_trade=concentration(i.by_trade) if i.by_trade else None,
        oos_days=float(len(oos)) if oos else None,
        regimes=float(len(set(i.regime_labels))) if i.regime_labels else None,
        window_share=max(gains) / sum(gains) if gains else None,
    )

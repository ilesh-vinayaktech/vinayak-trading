# ruff: noqa: E501
"""Turn a finished study's trials into evidence for the pass/fail gates. Pure: it takes the stored daily returns of every
parameter combination (research window only) and nothing else, so the same trials always give the same verdict.

How the evidence is made:
- walk-forward: in each rolling window the combination with the best Sharpe on the TRAIN days is chosen and judged on the
  next TEST days (after an embargo). Only those test days count as out-of-sample. The stored returns are sliced, nothing is re-run.
- overfitting probability: every combination's return series, split into blocks (CSCV).
- parameter plateau: the best combination over the whole research window against its neighbours one step away in the grid.
- regimes: the calendar year of each out-of-sample day (a stand-in until real regime labels exist).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Any

from algo.backtest.report import Trip
from algo.backtest.validation import mc_bootstrap, registry
from algo.backtest.validation.evidence import Inputs
from algo.backtest.validation.gates import Thresholds
from algo.backtest.validation.stats import (
    TRADING_DAYS,
    annualised_sharpe,
    max_drawdown,
    sharpe_per_period,
)
from algo.backtest.validation.walkforward import walk_forward, windows

TRAIN, TEST, EMBARGO = (
    504,
    126,
    5,
)  # sessions: about two years to choose, six months to judge, a week apart


class VerdictError(ValueError):
    pass


@dataclass(frozen=True)
class Analysis:
    base: dict[str, Any]  # the best combination over the whole research window
    base_sharpe: float | None
    neighbour_sharpes: list[float | None]
    oos_returns: list[float]
    window_returns: list[float]
    benchmark_oos: list[float]
    regime_labels: list[str]
    windows: list[
        dict[str, Any]
    ]  # per window: dates, chosen settings, Sharpe and return judged out of sample
    selected: bool = (
        True  # False when the setting was fixed in advance: nothing was chosen on past data
    )


def _compound(rs: Sequence[float]) -> float:
    total = 1.0
    for r in rs:
        total *= 1 + r
    return total - 1


def _key(p: Mapping[str, Any]) -> str:
    return registry.params_hash(p)


def neighbours(
    base: Mapping[str, Any], grid: Mapping[str, Sequence[float]]
) -> list[dict[str, Any]]:
    """The combinations one step away from `base` in the grid, one setting at a time."""
    out = []
    for name, values in grid.items():
        vs = sorted(values)
        i = vs.index(base[name])
        out += [{**base, name: vs[j]} for j in (i - 1, i + 1) if 0 <= j < len(vs)]
    return out


def analyse(
    days: Sequence[date],
    combos: Sequence[Mapping[str, Any]],
    returns: Mapping[str, Sequence[float]],
    grid: Mapping[str, Sequence[float]],
    benchmark: Sequence[float] | None = None,
    fixed: Mapping[str, Any] | None = None,
) -> Analysis:
    """`days`: the session dates of the equity curve; `returns[hash][i]` is the return on days[i + 1]. With `fixed` (a combination decided before the study) nothing is chosen on past data:
    that setting is judged on the same out-of-sample days walk-forward would use, and the plateau compares it with its neighbours."""
    n = len(days) - 1
    missing = [c for c in combos if _key(c) not in returns]
    if missing:
        raise VerdictError(
            f"{len(missing)} combination(s) have no finished trial: run all trials first"
        )
    if any(len(returns[_key(c)]) != n for c in combos):
        raise VerdictError("the trials cover different days, so they cannot be compared")
    if benchmark is not None and len(benchmark) != n:
        raise VerdictError("the benchmark returns do not line up with the trial days")
    if not windows(n, TRAIN, TEST, EMBARGO):
        raise VerdictError(
            f"{n} sessions is too short for walk-forward: it needs at least {TRAIN + EMBARGO + TEST}"
        )
    if fixed is not None and not any(_key(c) == _key(fixed) for c in combos):
        raise VerdictError(f"the fixed setting {dict(fixed)} is not one of the combinations")
    wins = windows(n, TRAIN, TEST, EMBARGO)
    if fixed is None:
        wf = walk_forward(
            n,
            list(combos),
            lambda p, s, e: returns[_key(p)][s:e],
            train=TRAIN,
            test=TEST,
            embargo=EMBARGO,
        )
        chosen_each, sharpe_each, oos_out = (
            list(wf.chosen),
            list(wf.per_window_sharpe),
            list(wf.oos_returns),
        )
    else:  # nothing selected: the same setting in every window
        chosen_each = [dict(fixed) for _ in wins]
        sharpe_each = [sharpe_per_period(returns[_key(fixed)][w.test[0] : w.test[1]]) for w in wins]
        oos_out = [r for w in wins for r in returns[_key(fixed)][w.test[0] : w.test[1]]]
    oos_idx = [i for w in wins for i in range(*w.test)]
    rows, window_returns = [], []
    for w, chosen, sh in zip(wins, chosen_each, sharpe_each, strict=True):
        r = returns[_key(chosen)][w.test[0] : w.test[1]]
        window_returns.append(_compound(r))
        rows.append({
            "train_from": str(days[w.train[0] + 1]), "train_to": str(days[w.train[1]]),
            "test_from": str(days[w.test[0] + 1]), "test_to": str(days[w.test[1]]),
            "chosen": dict(chosen), "sharpe": None if sh is None else sh * sqrt(TRADING_DAYS),
            "return": window_returns[-1],
        })  # fmt: skip
    best = max(
        range(len(combos)),
        key=lambda i: (
            (s := sharpe_per_period(returns[_key(combos[i])])) is not None,
            s or 0.0,
            -i,
        ),
    )
    base = dict(fixed) if fixed is not None else dict(combos[best])
    near = [returns.get(_key(c)) for c in neighbours(base, grid)]
    return Analysis(
        base=base,
        base_sharpe=annualised_sharpe(returns[_key(base)]),
        neighbour_sharpes=[None if r is None else annualised_sharpe(r) for r in near],
        oos_returns=oos_out,
        window_returns=window_returns,
        benchmark_oos=[] if benchmark is None else [benchmark[i] for i in oos_idx],
        regime_labels=[str(days[i + 1].year) for i in oos_idx],
        windows=rows,
        selected=fixed is None,
    )


def contributions(
    trips: Sequence[Trip],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Net profit by stock, by month of sale and by trade, for the concentration gates."""
    stock: dict[str, float] = defaultdict(float)
    month: dict[str, float] = defaultdict(float)
    trade: dict[str, float] = {}
    for k, t in enumerate(trips):
        stock[str(t.instrument_id)] += float(t.net)
        month[t.exit_day.strftime("%Y-%m")] += float(t.net)
        trade[str(k)] = float(t.net)
    return dict(stock), dict(month), trade


def inputs(
    a: Analysis,
    *,
    n_trials: int,
    trial_sharpes: Sequence[float],
    trial_returns: Sequence[Sequence[float]],
    plateau_tolerance: float,
    returns_2x_costs: Sequence[float],
    returns_3x_capital: Sequence[float],
    trips: Sequence[Trip],
) -> Inputs:
    stock, month, trade = contributions(trips)
    return Inputs(
        oos_returns=a.oos_returns,
        window_returns=a.window_returns,
        regime_labels=a.regime_labels,
        benchmark_returns=a.benchmark_oos,
        n_trials=n_trials,
        trial_sharpes=trial_sharpes,
        trial_returns=trial_returns,
        base_sharpe=a.base_sharpe,
        neighbour_sharpes=a.neighbour_sharpes,
        plateau_tolerance=plateau_tolerance,
        returns_2x_costs=returns_2x_costs,
        returns_3x_capital=returns_3x_capital,
        by_instrument=stock,
        by_month=month,
        by_trade=trade,
        no_selection=not a.selected,
    )


def holdout_gates(
    returns: Sequence[float], benchmark: Sequence[float] | None, t: Thresholds
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The one-time test on days the study never saw: the chosen settings must still clear the owner's bar for out-of-sample
    Sharpe and drawdown, and beat the index by the same margin. Returns the gates and the figures behind them."""
    sharpe = annualised_sharpe(list(returns))
    bench = annualised_sharpe(list(benchmark)) if benchmark is not None else None
    dd = abs(max_drawdown(list(returns))) if returns else None
    gates: list[dict[str, Any]] = []

    def gate(name: str, value: float | None, ok: bool, detail: str) -> None:
        gates.append(
            {
                "name": name,
                "passed": value is not None and ok,
                "detail": "evidence missing" if value is None else detail,
                "status": "INSUFFICIENT_EVIDENCE" if value is None else ("PASS" if ok else "FAIL"),
            }
        )

    gate(
        "holdout_sharpe",
        sharpe,
        (sharpe or 0) >= t.min_oos_sharpe,
        f"{sharpe or 0:.2f} < required {t.min_oos_sharpe}",
    )
    gate(
        "holdout_drawdown",
        dd,
        (dd or 0) <= t.owner_max_drawdown,
        f"{(dd or 0):.1%} > owner cap {t.owner_max_drawdown:.0%}",
    )
    edge = None if sharpe is None or bench is None else sharpe - bench
    gate(
        "holdout_beats_benchmark",
        edge,
        (edge or 0) >= t.min_sharpe_over_benchmark,
        f"edge over the index {(edge or 0):.2f} < required {t.min_sharpe_over_benchmark}",
    )
    evidence = {"days": len(returns), "sharpe": sharpe, "max_drawdown": None if dd is None else -dd, "benchmark_sharpe": bench,
                "total_return": math.prod(1 + r for r in returns) - 1 if returns else None}  # fmt: skip
    return gates, evidence


HOLDOUT_ALPHA = (
    0.05 / 30
)  # docs/holdout-policy-v3.md section 2: 5% family-wise over the dataset's whole budget of 30 candidates (holdout_batch.BUDGET)
HOLDOUT_DRAWS = 1_000_000
V3_GATES = ("holdout_significance", "holdout_sharpe", "holdout_drawdown", "holdout_beats_benchmark")


def holdout_gates_v3(
    returns: Sequence[float],
    benchmark: Sequence[float] | None,
    t: Thresholds,
    *,
    seed: int,
    draws: int = HOLDOUT_DRAWS,
    alpha: float = HOLDOUT_ALPHA,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The acceptance decision of a holdout batch candidate (policy v3 section 2). A candidate PASSES only if the corrected primary test rejects "true Sharpe <= 0"
    (Monte Carlo p-value at `alpha`, with the candidate's own committed `seed`) AND the three floors hold: Sharpe, drawdown at most `max_drawdown_vs_benchmark` times the
    index's over the same dates, and the Sharpe edge over the index. The floors can only remove passes. Evidence that is missing (no index, misaligned index, an index
    with no drawdown, returns the test cannot use) is INSUFFICIENT_EVIDENCE, never a pass and never replaced by another rule."""
    r = list(returns)
    aligned = benchmark is not None and len(benchmark) == len(r)
    bench = list(benchmark) if benchmark is not None and aligned else None
    sharpe = annualised_sharpe(r)
    bench_sharpe = annualised_sharpe(bench) if bench is not None else None
    dd = abs(max_drawdown(r)) if r else None
    bench_dd = abs(max_drawdown(bench)) if bench else None
    ratio = None if dd is None or not bench_dd else dd / bench_dd
    edge = None if sharpe is None or bench_sharpe is None else sharpe - bench_sharpe
    result: mc_bootstrap.Result | None
    try:
        result = mc_bootstrap.test(r, seed, draws)
    except ValueError:
        result = None
    gates: list[dict[str, Any]] = []

    def gate(name: str, value: float | None, ok: bool, detail: str) -> None:
        gates.append(
            {
                "name": name,
                "passed": value is not None and ok,
                "detail": "evidence missing" if value is None else detail,
                "status": "INSUFFICIENT_EVIDENCE" if value is None else ("PASS" if ok else "FAIL"),
            }
        )

    p = None if result is None else result.p
    gate("holdout_significance", p, (p or 1) <= alpha, f"p {(p or 1):.6f} > {alpha:.6f}")
    gate(
        "holdout_sharpe",
        sharpe,
        (sharpe or 0) >= t.min_oos_sharpe,
        f"{sharpe or 0:.2f} < required {t.min_oos_sharpe}",
    )
    gate(
        "holdout_drawdown",
        ratio,
        (ratio or 0) <= t.max_drawdown_vs_benchmark + 1e-9,
        f"drawdown is {(ratio or 0):.2f}x the index's (limit {t.max_drawdown_vs_benchmark})",
    )
    gate(
        "holdout_beats_benchmark",
        edge,
        (edge or 0) >= t.min_sharpe_over_benchmark,
        f"edge over the index {(edge or 0):.2f} < required {t.min_sharpe_over_benchmark}",
    )
    evidence = {
        "days": len(r), "sharpe": sharpe, "max_drawdown": None if dd is None else -dd, "benchmark_sharpe": bench_sharpe,
        "benchmark_max_drawdown": None if bench_dd is None else -bench_dd, "drawdown_ratio": ratio,
        "total_return": math.prod(1 + x for x in r) - 1 if r else None,
        "k": None if result is None else result.k, "draws": draws, "p_mc": p, "alpha": alpha, "seed": f"{seed:032x}",
    }  # fmt: skip
    return gates, evidence

# ruff: noqa: E501
"""The pass/fail decision. Every gate needs its evidence; MISSING evidence FAILS the gate (a check
that was not run is not a check that passed) and is reported as INSUFFICIENT_EVIDENCE, distinct from
a measured FAIL. Thresholds are data
(config/validation_thresholds.json) and are fixed BEFORE a strategy is validated."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    min_oos_sharpe: float  # annualised, net of costs, aggregate walk-forward OOS
    min_dsr: float
    max_pbo: float
    max_drawdown_vs_benchmark: float  # |strategy max DD| / |benchmark max DD|, same dates
    owner_max_drawdown: float  # absolute cap, fraction (0.25 = 25%)
    plateau_tolerance: float  # worst neighbour must keep >= (1 - tol) of the base Sharpe
    max_top3_concentration: float  # applied separately to instruments, months and trades
    min_sharpe_over_benchmark: float  # strategy annualised Sharpe minus benchmark's
    min_oos_days: float
    min_regimes: float
    max_window_share: float  # largest single walk-forward window's share of positive window gains
    min_benchmark_drawdown: float  # below this the drawdown ratio is unstable: not applicable


def load_thresholds(path: Path, style: str) -> tuple[Thresholds, str]:
    """Returns (thresholds, status). style: 'long_only' | 'market_neutral'."""
    doc = json.loads(path.read_text())
    if style not in doc:
        raise ValueError(f"no thresholds for style {style!r}")
    raw = doc[style]
    names = {f.name for f in fields(Thresholds)}
    if set(raw) != names:
        raise ValueError(f"threshold keys differ from expected: {sorted(set(raw) ^ names)}")
    return Thresholds(**{k: float(v) for k, v in raw.items()}), doc.get("status", "")


@dataclass(frozen=True)
class Evidence:
    oos_sharpe: float | None = None
    dsr: float | None = None
    pbo: float | None = None
    max_drawdown: float | None = None  # negative fraction
    benchmark_max_drawdown: float | None = None  # negative fraction, same dates and frequency
    benchmark_sharpe: float | None = None
    plateau_drop: float | None = None  # worst fractional Sharpe loss across +/-20% parameters
    sharpe_2x_costs: float | None = None
    sharpe_3x_capital: float | None = None
    top3_instrument: float | None = None  # share of total positive P&L from the 3 best instruments
    top3_month: float | None = None
    top3_trade: float | None = None
    oos_days: float | None = None
    regimes: float | None = None  # distinct market regimes inside the OOS windows
    window_share: float | None = None
    # when every tried variant is nearly the same strategy (a grid over portfolio size and exit share), the overfitting probability says nothing: it is
    # replaced by the lower bound of a bootstrap interval on the out-of-sample Sharpe, which must be above zero (review 2026-11-16, section 3.2)
    pbo_twins: bool = False
    oos_sharpe_lower: float | None = (
        None  # lower end of the 90% bootstrap interval of the annualised out-of-sample Sharpe
    )


STATUSES = ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE")


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str
    missing: bool = False  # the evidence was not measured at all

    @property
    def status(self) -> str:
        """PASS or FAIL when measured, INSUFFICIENT_EVIDENCE when not. (NOT_APPLICABLE is in the
        vocabulary for gates that do not apply by design; none does today.) Missing evidence is
        never read as a weak pass."""
        if self.missing:
            return "INSUFFICIENT_EVIDENCE"
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class Report:
    gates: tuple[Gate, ...]
    thresholds_status: str

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def failures(self) -> list[str]:
        return [f"{g.name}: {g.detail}" for g in self.gates if not g.passed]

    @property
    def statuses(self) -> dict[str, str]:
        return {g.name: g.status for g in self.gates}

    @property
    def insufficient(self) -> list[str]:
        """The gates that could not be judged because their evidence was never measured."""
        return [g.name for g in self.gates if g.missing]


def _gate(name: str, value: float | None, ok, detail: str) -> Gate:  # type: ignore[no-untyped-def]
    if value is None:
        return Gate(name, False, "evidence missing", missing=True)
    return Gate(name, bool(ok(value)), detail.format(v=value))


def _drawdown_gate(e: Evidence, t: Thresholds) -> Gate:
    if e.max_drawdown is None or e.benchmark_max_drawdown is None:
        return Gate("max_drawdown", False, "evidence missing", missing=True)
    dd, bench = abs(e.max_drawdown), abs(e.benchmark_max_drawdown)
    if dd > t.owner_max_drawdown:
        return Gate("max_drawdown", False, f"{dd:.1%} > owner cap {t.owner_max_drawdown:.0%}")
    if bench < t.min_benchmark_drawdown:  # ratio unstable: only the absolute cap applies
        return Gate("max_drawdown", True, f"{dd:.1%}; ratio n/a (benchmark DD {bench:.1%})")
    ratio = dd / bench
    ok = ratio <= t.max_drawdown_vs_benchmark + 1e-9
    return Gate(
        "max_drawdown",
        ok,
        f"{dd:.1%} is {ratio:.2f}x benchmark (limit {t.max_drawdown_vs_benchmark})",
    )


def _overfitting_gate(e: Evidence, t: Thresholds) -> Gate:
    if e.pbo_twins:  # the tried variants are near-identical: PBO is not meaningful, so the bootstrap bound on the Sharpe decides
        return _gate("overfitting_probability", e.oos_sharpe_lower, lambda v: v > 0,
                     "variants are near-identical (PBO not meaningful); the lower end of the 90% bootstrap interval of the out-of-sample Sharpe is {v:.2f} (must be above 0)")  # fmt: skip
    return _gate(
        "overfitting_probability",
        e.pbo,
        lambda v: v <= t.max_pbo,
        f"{{v:.2f}} > allowed {t.max_pbo}",
    )


def evaluate(e: Evidence, t: Thresholds, status: str = "") -> Report:
    over_bench = (
        None if e.oos_sharpe is None or e.benchmark_sharpe is None
        else e.oos_sharpe - e.benchmark_sharpe
    )  # fmt: skip
    top = t.max_top3_concentration
    gates = (
        _gate("oos_days", e.oos_days, lambda v: v >= t.min_oos_days,
              f"{{v:.0f}} OOS observations < required {t.min_oos_days:.0f}"),
        _gate("regimes", e.regimes, lambda v: v >= t.min_regimes,
              f"{{v:.0f}} regimes < required {t.min_regimes:.0f}"),
        _gate("window_share", e.window_share, lambda v: v <= t.max_window_share,
              f"one window supplies {{v:.0%}} of gains (> {t.max_window_share:.0%})"),
        _gate("oos_sharpe", e.oos_sharpe, lambda v: v >= t.min_oos_sharpe,
              f"{{v:.2f}} < required {t.min_oos_sharpe}"),
        _gate("deflated_sharpe", e.dsr, lambda v: v >= t.min_dsr,
              f"{{v:.3f}} < required {t.min_dsr}"),
        _overfitting_gate(e, t),
        _drawdown_gate(e, t),
        _gate("beats_benchmark", over_bench, lambda v: v >= t.min_sharpe_over_benchmark,
              f"Sharpe edge over benchmark {{v:.2f}} < required {t.min_sharpe_over_benchmark}"),
        _gate("parameter_plateau", e.plateau_drop, lambda v: v <= t.plateau_tolerance,
              f"{{v:.0%}} Sharpe lost at a neighbouring setting (> {t.plateau_tolerance:.0%})"),
        _gate("survives_2x_costs", e.sharpe_2x_costs, lambda v: v > 0,
              "Sharpe {v:.2f} at 2x costs"),
        _gate("survives_3x_capital", e.sharpe_3x_capital, lambda v: v > 0,
              "Sharpe {v:.2f} at 3x capital"),
        _gate("concentration_instrument", e.top3_instrument, lambda v: v <= top,
              f"{{v:.0%}} of gains from 3 instruments (> {top:.0%})"),
        _gate("concentration_month", e.top3_month, lambda v: v <= top,
              f"{{v:.0%}} of gains from 3 months (> {top:.0%})"),
        _gate("concentration_trade", e.top3_trade, lambda v: v <= top,
              f"{{v:.0%}} of gains from 3 trades (> {top:.0%})"),
    )  # fmt: skip
    return Report(gates, status)

"""The pass/fail decision. Every gate needs its evidence; MISSING evidence FAILS the gate (a check
that was not run is not a check that passed). Thresholds are data
(config/validation_thresholds.json) and are fixed BEFORE a strategy is validated."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Thresholds:
    min_oos_sharpe: float
    min_dsr: float
    max_pbo: float
    max_drawdown_vs_benchmark: float
    owner_max_drawdown: float  # fraction, e.g. 0.35 = 35%
    plateau_tolerance: float
    max_top3_concentration: float
    min_sharpe_over_benchmark: float


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
    oos_sharpe: float | None = None  # annualised, net of realistic costs, walk-forward OOS
    dsr: float | None = None
    pbo: float | None = None
    max_drawdown: float | None = None  # negative fraction
    benchmark_max_drawdown: float | None = None  # negative fraction
    benchmark_sharpe: float | None = None
    plateau_drop: float | None = None  # worst fractional Sharpe loss across +/-20% parameters
    sharpe_2x_costs: float | None = None
    sharpe_3x_capital: float | None = None
    top3_concentration: float | None = None


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str


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


def _gate(name: str, value: float | None, ok, detail: str) -> Gate:  # type: ignore[no-untyped-def]
    if value is None:
        return Gate(name, False, "evidence missing")
    return Gate(name, bool(ok(value)), detail.format(v=value))


def evaluate(e: Evidence, t: Thresholds, status: str = "") -> Report:
    dd_limit: float | None = None
    if e.benchmark_max_drawdown is not None:
        dd_limit = min(
            abs(e.benchmark_max_drawdown) * t.max_drawdown_vs_benchmark, t.owner_max_drawdown
        )
    over_bench = (
        None if e.oos_sharpe is None or e.benchmark_sharpe is None
        else e.oos_sharpe - e.benchmark_sharpe
    )  # fmt: skip
    gates = (
        _gate("oos_sharpe", e.oos_sharpe, lambda v: v >= t.min_oos_sharpe,
              f"{{v:.2f}} < required {t.min_oos_sharpe}"),
        _gate("deflated_sharpe", e.dsr, lambda v: v >= t.min_dsr,
              f"{{v:.3f}} < required {t.min_dsr}"),
        _gate("overfitting_probability", e.pbo, lambda v: v <= t.max_pbo,
              f"{{v:.2f}} > allowed {t.max_pbo}"),
        _gate("max_drawdown",
              None if e.max_drawdown is None or dd_limit is None else abs(e.max_drawdown),
              lambda v: v <= (dd_limit or 0), f"{{v:.1%}} > limit {dd_limit}"),
        _gate("beats_benchmark", over_bench, lambda v: v > t.min_sharpe_over_benchmark,
              "Sharpe edge over benchmark {v:.2f} too small"),
        _gate("parameter_plateau", e.plateau_drop, lambda v: v <= t.plateau_tolerance,
              f"{{v:.0%}} Sharpe lost at a neighbouring setting (> {t.plateau_tolerance:.0%})"),
        _gate("survives_2x_costs", e.sharpe_2x_costs, lambda v: v > 0,
              "Sharpe {v:.2f} at 2x costs"),
        _gate("survives_3x_capital", e.sharpe_3x_capital, lambda v: v > 0,
              "Sharpe {v:.2f} at 3x capital"),
        _gate("concentration", e.top3_concentration, lambda v: v <= t.max_top3_concentration,
              f"{{v:.0%}} of gains from 3 items (> {t.max_top3_concentration:.0%})"),
    )  # fmt: skip
    return Report(gates, status)

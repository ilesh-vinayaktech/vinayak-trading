# ruff: noqa: E501
"""Capital allocation across approved strategies (plan.md section 14): a RECOMMENDATION from their daily returns, within hard limits.

Callers: tests/unit/portfolio/test_allocation.py; no production caller yet. User's instruction: "do as much as you can do yourself, keep taking things one by one
from @TODO.md and @plan.md ... keep things finishing with test". Pure: it is handed {strategy: daily returns} (equal length, same days) and the health of each, and
returns weights; it moves no money and changes no strategy's status.
  * Methods: EQUAL_RISK (inverse volatility, correlations ignored) and RISK_PARITY (each strategy contributes the same share of portfolio variance).
  * Hard limits, applied last and never relaxed: no strategy above `max_single` (default 35%), weights add to at most `max_total` (default 100%, no leverage); what
    the cap cannot place stays in CASH rather than breaking a limit. A DEGRADED or unknown-health strategy gets zero; INSUFFICIENT and WATCH are kept (a person decides).
  * Volatility targeting only ever scales DOWN (a scale above 1 would be leverage): the weights shrink and the rest is cash."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

MIN_DAYS = 20


class AllocationError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_single: float = 0.35
    max_total: float = 1.0

    def validate(self) -> None:
        if not 0 < self.max_single <= 1 or not 0 < self.max_total <= 1:
            raise AllocationError("limits must be in (0, 1]: no leverage")


@dataclass(frozen=True)
class Allocation:
    weights: dict[str, float]
    cash: float
    notes: list[str] = field(default_factory=list)
    risk_contribution: dict[str, float] = field(default_factory=dict)


def _mean(x: Sequence[float]) -> float:
    return sum(x) / len(x)


def covariance(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise AllocationError("two return series of the same length (at least 2) are needed")
    ma, mb = _mean(a), _mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (len(a) - 1)


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson; None when either series does not vary."""
    va, vb = covariance(a, a), covariance(b, b)
    if va == 0 or vb == 0:
        return None
    return max(-1.0, min(1.0, covariance(a, b) / math.sqrt(va * vb)))


def risk_contributions(
    weights: Mapping[str, float], cov: Mapping[str, Mapping[str, float]]
) -> dict[str, float]:
    """Each strategy's share of portfolio variance (adds to 1 when the portfolio has any variance, else all zero)."""
    names = list(weights)
    marginal = {i: sum(weights[j] * cov[i][j] for j in names) for i in names}
    total = sum(weights[i] * marginal[i] for i in names)
    if total <= 0:
        return dict.fromkeys(names, 0.0)
    return {i: weights[i] * marginal[i] / total for i in names}


def cap_weights(weights: Mapping[str, float], limits: Limits) -> dict[str, float]:
    """Scale to at most max_total, then clip at max_single, passing the excess to the uncapped in proportion; whatever cannot be placed is left out (cash)."""
    w = dict(weights)
    total = sum(w.values())
    if total > limits.max_total:
        w = {k: v * limits.max_total / total for k, v in w.items()}
    while True:  # each pass caps at least one more strategy, so it ends
        over = {k for k, v in w.items() if v > limits.max_single + 1e-12}
        if not over:
            break
        excess = sum(w[k] - limits.max_single for k in over)
        for k in over:
            w[k] = limits.max_single
        room = {k: v for k, v in w.items() if k not in over and v < limits.max_single and v > 0}
        base = sum(room.values())
        if base == 0:
            break
        for k, v in room.items():
            w[k] = min(limits.max_single, v + excess * v / base)
    return w


def _risk_parity(
    names: list[str], cov: Mapping[str, Mapping[str, float]], iterations: int = 500
) -> dict[str, float]:
    w = {n: 1 / len(names) for n in names}
    for _ in range(iterations):
        marginal = {i: sum(w[j] * cov[i][j] for j in names) for i in names}
        if any(m <= 0 for m in marginal.values()):
            raise AllocationError(
                "risk parity needs strategies whose risk adds up to something positive"
            )
        raw = {
            i: 1 / marginal[i] for i in names
        }  # equal contributions mean weight x marginal risk is the same for all: weight ~ 1/marginal
        s = sum(raw.values())
        new = {i: 0.5 * w[i] + 0.5 * raw[i] / s for i in names}
        if max(abs(new[i] - w[i]) for i in names) < 1e-12:
            return new
        w = new
    raise AllocationError("risk parity did not converge")


def recommend(
    returns: Mapping[str, Sequence[float]],
    health: Mapping[str, str],
    *,
    method: str = "RISK_PARITY",
    limits: Limits | None = None,
    target_vol: float | None = None,
) -> Allocation:
    limits = limits or Limits()
    limits.validate()
    if method not in ("EQUAL_RISK", "RISK_PARITY"):
        raise AllocationError("method must be EQUAL_RISK or RISK_PARITY")
    lengths = {len(r) for r in returns.values()}
    if len(lengths) > 1:
        raise AllocationError("every strategy needs the same days of returns")
    notes: list[str] = []
    live = []
    for name in sorted(returns):
        if health.get(name) in ("OK", "WATCH", "INSUFFICIENT"):
            live.append(name)
        else:
            notes.append(f"{name}: {health.get(name, 'unknown health')}, given no capital")
    weights = dict.fromkeys(returns, 0.0)
    if not live:
        return Allocation(weights, 1.0, [*notes, "no strategy is eligible: all cash"])
    if any(len(returns[n]) < MIN_DAYS for n in live):
        raise AllocationError(f"at least {MIN_DAYS} days of returns per strategy are needed")
    cov = {i: {j: covariance(returns[i], returns[j]) for j in live} for i in live}
    if any(cov[i][i] <= 0 for i in live):
        raise AllocationError("a strategy with no variation cannot be sized by risk")
    if method == "EQUAL_RISK" or len(live) == 1:
        inv = {i: 1 / math.sqrt(cov[i][i]) for i in live}
        s = sum(inv.values())
        base = {i: inv[i] / s for i in live}
    else:
        base = _risk_parity(live, cov)
    placed = cap_weights(base, limits)
    if target_vol is not None:
        if target_vol <= 0:
            raise AllocationError("target_vol must be positive")
        port_var = sum(placed[i] * placed[j] * cov[i][j] for i in live for j in live)
        if port_var > 0 and math.sqrt(port_var) > target_vol:
            scale = target_vol / math.sqrt(port_var)
            placed = {k: v * scale for k, v in placed.items()}
            notes.append(f"scaled down by {scale:.3f} to the volatility target")
    weights.update(placed)
    cash = 1.0 - sum(weights.values())
    if cash > 1e-9 and sum(base.values()) > 0:
        notes.append(f"{cash:.1%} left in cash by the limits")
    rc = risk_contributions(placed, cov)
    return Allocation(weights, max(cash, 0.0), notes, rc)

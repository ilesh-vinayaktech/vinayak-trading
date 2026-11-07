"""Promotion gate. A research-mode backtest can never, by itself, authorize paper or live."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunSummary:
    reader_mode: str
    provisional_events: int
    unapplied_events: int
    accounting_complete: bool  # every held corporate action was modelled
    placeholder_costs: bool
    validation_protocol_passed: bool  # walk-forward, deflated Sharpe, ... (not built yet)
    ledger_reconciled: bool  # the financial ledger agrees with itself (cash, positions, P&L)


def promotion_blockers(run: RunSummary) -> list[str]:
    """Reasons this run cannot support moving a strategy beyond research. Empty = eligible."""
    out = []
    if run.reader_mode != "strict":
        out.append("run was not made in strict reader mode")
    if run.provisional_events:
        out.append(
            f"{run.provisional_events} provisional (unverified) corporate-action estimates used"
        )
    if run.unapplied_events:
        out.append(f"{run.unapplied_events} unpriced corporate actions affect the prices")
    if not run.accounting_complete:
        out.append("held positions passed through corporate actions the accounting cannot model")
    if not run.ledger_reconciled:
        out.append("financial ledger does not reconcile")
    if run.placeholder_costs:
        out.append("placeholder cost model: costs are not the versioned cost schedule")
    if not run.validation_protocol_passed:
        out.append("validation protocol (walk-forward, deflated Sharpe, ...) has not passed")
    return out

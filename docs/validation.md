# Validation protocol

A backtest number is only evidence after it survives the checks below. Code: `src/algo/backtest/validation/`.

| Step | Module | What it answers |
|---|---|---|
| Pre-register | `registry.register` | Hypothesis, parameter ranges and a holdout window are written down before any trial. |
| Count trials | `registry.record_trial` | N = distinct configurations tried (same params twice is one trial). Params outside the registered ranges are refused. |
| Development window | `registry.assert_research_window` | Development runs must end before the holdout starts. |
| Walk-forward | `walkforward.walk_forward` | Choose params on train, judge on the next window; embargo gap between them. |
| Deflated Sharpe | `stats.deflated_sharpe` | Probability the true Sharpe beats what luck gives after N tries (Bailey and Lopez de Prado). |
| PBO | `stats.pbo_cscv` | How often the in-sample winner ranks at or below the OOS median. |
| Bootstrap | `stats.bootstrap_interval` | Stationary-bootstrap CIs for Sharpe and max drawdown (seeded, reproducible). |
| Robustness | `robustness.*` | ±20% parameter plateau (within 30%), by-year breakdown, top-3 concentration. |
| Cost stress | `costs.scaled.ScaledCosts` | Re-run at 2x charges and slippage; must stay positive. |
| Holdout | `registry.open_holdout` | Opened once, atomically; the second attempt raises. |
| Decide | `gates.evaluate` | Nine gates. **Missing evidence fails its gate.** |
| Record | `registry.save_report` | Evidence, per-gate result, N and the thresholds' status are stored. |

Thresholds are data (`config/validation_thresholds.json`). They ship as `provisional`; `validation_passed()` only
counts a passing report made against `confirmed` thresholds, so nothing can be promoted until the owner has
confirmed them. Do not change them after seeing a result.

Not built yet: the orchestrator that feeds a real strategy through all steps and assembles `Evidence`
(arrives with the first strategy), benchmark loader, 3x-capital run, purged CV for ML.

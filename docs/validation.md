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
| Decide | `gates.evaluate` | Fourteen gates (definitions below). **Missing evidence fails its gate.** |
| Record | `registry.save_report` | Evidence, per-gate result, N and the thresholds' status are stored. |

Thresholds are data (`config/validation_thresholds.json`). They ship as `provisional`; `validation_passed()` only
counts a passing report made against `confirmed` thresholds, so nothing can be promoted until the owner has
confirmed them. Do not change them after seeing a result.

Not built yet: the orchestrator that feeds a real strategy through all steps and assembles `Evidence`
(arrives with the first strategy), benchmark loader, 3x-capital run, purged CV for ML.

## Gate definitions (thresholds v2, provisional)

| Gate | Exact rule |
|---|---|
| oos_days | Aggregate walk-forward OOS observations >= `min_oos_days` (252). Serial correlation and overlap can make the effective sample smaller. |
| regimes | Distinct market regimes represented in the OOS windows >= `min_regimes` (2). |
| window_share | Largest single walk-forward window's share of the positive window gains <= `max_window_share` (0.5). Per-window results are reported, not just the aggregate. |
| oos_sharpe | Annualised, net of all costs, aggregate OOS >= `min_oos_sharpe`. |
| deflated_sharpe | DSR >= `min_dsr`, with N = the registry's trial count. |
| overfitting_probability | PBO (CSCV) <= `max_pbo` (0.2). |
| max_drawdown | `abs(strategy DD) <= owner_max_drawdown` AND `abs(strategy DD) / abs(benchmark DD) <= max_drawdown_vs_benchmark`, same dates and frequency. If the benchmark DD is below `min_benchmark_drawdown` the ratio is unstable and not applied; the absolute cap still is. |
| beats_benchmark | Strategy annualised Sharpe minus benchmark annualised Sharpe >= `min_sharpe_over_benchmark`. Market-neutral strategies use a cash/risk-free benchmark and also report beta. |
| parameter_plateau | Worst +/-20% neighbour keeps >= (1 - `plateau_tolerance`) of the base Sharpe. An undefined neighbour counts as a collapse. (Drawdown and turnover of neighbours are not yet checked.) |
| survives_2x_costs / 3x_capital | Sharpe > 0 at 2x charges+slippage / at 3x capital. |
| concentration_instrument / month / trade | Share of total positive P&L from the 3 best instruments / months / trades <= `max_top3_concentration`, each reported and gated separately. |

Missing evidence fails its gate. Passing means the research-validation policy passed; it does not mean ready for live
capital (paper trading, broker reconciliation and operational controls are separate promotion requirements).
The thresholds were set before any strategy was tried; if the first strategy fails, that is a research result, not
a reason to change them.

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

Thresholds are data (`config/validation_thresholds.json`). `validation_passed()` only counts a passing report made
against `confirmed` thresholds. The owner confirmed the current set on 2026-11-12, before any strategy was validated
("keep it, we will improve over time"). Do not change them after seeing a result: an improvement is a new version used by
later studies.

## The study verdict (`algo.research.verdict`, `study_runner.run_verdict`)

A backtest study's "Judge the results" runs this over the finished trials. It never reads the holdout.

| Evidence | How it is made |
|---|---|
| Out-of-sample returns | Walk-forward over the research window using the stored daily returns of every combination: train 504 sessions, embargo 5, test 126, stepping by 126. The best train-Sharpe combination in each window is judged only on its test days. Nothing is re-run. |
| Deflated Sharpe | The out-of-sample returns, N = the registry's trial count, variance across the trials' Sharpes. |
| Overfitting probability | CSCV over every combination's return series. |
| Plateau | The best combination over the whole research window against its neighbours one step away in the grid, one setting at a time (the grid is discrete, so this replaces "+/-20%"). A grid with one value per setting has no neighbours, so this gate fails for missing evidence. |
| Benchmark | The study's chosen total-return index (default Nifty 200 TRI gross), only if its stored data has a passing validation; otherwise its gates fail and the report says why. |
| 2x costs / 3x capital | The chosen combination re-run through the engine with every charge and slippage doubled, and with capital times the study's capacity multiple. These runs are saved, are not trials, and are linked from the report. |
| Concentration | Net profit by stock, by month of sale and by trade, from the chosen combination's closed trades (first in, first out). |
| Regimes | The calendar year of each out-of-sample day (a stand-in until real regime labels exist). |

The report (gates, evidence, chosen settings, every window, the stress runs) is stored in `validation_report`.

## Promotion (`algo.strategy.stage`, migration 048)

A saved strategy is in RESEARCH, PAPER or LIVE; every move is an append-only row with the approver, time, reason and (for
LIVE) the backtest run. RESEARCH to PAPER needs only a reason (the owner's waiver for unvalidated paper trading, recorded on
the row). PAPER to LIVE needs a run of this strategy with these settings and no `promotion_blockers`, which includes a
passing validation report against confirmed thresholds. RESEARCH cannot jump to LIVE; moving down is always allowed.
There is no live trading runner yet, so LIVE is a recorded stage that gates the future runner.

## Pinned data (`algo.data.snapshot`, `BarReader(known_at=...)`)

A reader pinned to a moment ignores bars, corporate actions and decisions ingested after it, so a provider's later
correction cannot change a rerun. `snapshot_hash` fingerprints exactly what was read; a pinned run stores
`{known_at, hash}` in its config.

## The holdout (`study_runner.run_holdout`, migration 049)

After a research verdict that passed every check, "Open the holdout" runs the chosen settings once over the holdout days
(`holdout_start` to the study's end). Three gates use the study's own thresholds: Sharpe >= `min_oos_sharpe`, drawdown <=
`owner_max_drawdown`, and Sharpe over the index >= `min_sharpe_over_benchmark` (missing evidence fails). It cannot be opened
before a passing verdict, and only once: `experiment.holdout_opened_at` is claimed in the same transaction that stores the
result in `study_holdout`. The holdout run is saved but is not a trial.

Not built yet: real regime labels, a 12-1 momentum baseline, purged CV for ML.

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

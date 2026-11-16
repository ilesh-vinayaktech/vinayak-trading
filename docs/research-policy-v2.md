# Research policy v2: single-configuration studies (applies from 2026-11-16)

Written for the owner. This is the protocol for the new round. It is a policy change made after the first round failed on the overfitting probability, so it applies ONLY to new studies
(named "... stop2 fixed"); the verdicts already recorded stand and are not re-judged.

## The two questions, kept apart

1. Does the strategy have an edge? (walk-forward, benchmark, drawdown, costs, capacity, neighbours, concentration)
2. Can we pick its best setting from past data? (the overfitting probability, PBO)

A study that CHOOSES among settings must answer both and keeps the PBO gate at 0.20. A study whose setting was fixed before it ran chooses nothing, so question 2 does not arise for it; it is judged on question 1,
and its overfitting gate asks instead that the lower end of a 90% bootstrap interval of the out-of-sample Sharpe is above zero. A pre-registered setting is NOT validated just because PBO no longer applies:
every other gate still applies unchanged.

## What is fixed before the study (and where it is recorded)

All of this is in the study document, which is locked with a checksum when the study is registered (`experiment.study`, `study_sha256`); it cannot be edited afterwards.

| Item | Fixed value | Recorded in |
|---|---|---|
| Strategy definition | Exact entry, exit, ranking, rebalance, sizing | the definition, by hash (`strategy_definition`), copied into the study |
| Setting | The definition's OWN written-down numbers (stocks held, the share it sells at), read from the definition, never from results (`algo.factory.study.own_setting`) | `spec.fixed` |
| Robustness grid | One step either side of the setting for each number (`grid_around`) | `spec.grid` |
| Universe | AMFI large + mid caps by the list in force each day; before 2018-08 the traded-value stand-in; 252 sessions of history | `spec.universe` |
| Costs | The Zerodha delivery schedule in force each day; 2x costs and 3x capital stress | cost schedules in the study document |
| Stops | 2% per-trade stop, 5-day re-entry cooldown, inside the backtest | `spec.trade_stop`, `stop_cooldown_days` |
| Evaluation | Walk-forward 504 sessions train, 126 test, 5 embargo; the fixed setting is judged on the same test days | `algo/research/verdict.py` |
| Acceptance | Thresholds v3 as they were on the day of registration | `spec.thresholds` |
| Robustness | Neighbour settings must keep at least 70% of the Sharpe (plateau tolerance 30%) | `spec.thresholds` |
| Holdout | 2025 onward untouched; opened once, only after a verdict that passed every gate | the research lock |
| Counting | Every try of the same idea counts toward the deflated Sharpe; the same definition, window, setting and stop counts once | `registry.deflation_trials` |

## Rules that stop the selection problem coming back

- **A robustness grid is a check, never a menu.** If the fixed setting fails, a different setting from the grid cannot be registered for the same definition, window and stop (enforced:
  `algo.factory.study.register` raises `ReplacementRefused`). A genuinely new idea is a new definition version, registered and hashed before it is run.
- **The setting is not chosen from the first round's results.** One finding from the diagnostic (MOMENTUM_LOWVOL_M: 30-stock variants rank consistently higher out of sample) is a hypothesis to test on its own
  with a pre-registered setting; it is not used to pick this round's setting.
- **PBO stays at 0.20 and the near-twin line at 0.9.** The block count for PBO is 8; 4, 6 and 10 are sensitivity checks and are never used to pick the most favourable number.
- **Survivorship and corporate actions** are checked as before; the survivorship before 2018-08 is an accepted, stated limitation (not yet removed).

## Open items this policy does not close

- Survivorship before 2018-08 (needs delisted names' prices).
- The new round is a first prospective test of the protocol, not proof of it: a few passing strategies out of five would not show the protocol works until it has been used on strategies not seen before.

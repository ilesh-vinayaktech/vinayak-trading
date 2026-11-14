# VTI alignment: how `plan.md` fits the platform that exists

Decided by the owner on 2026-11-14. `plan.md` is the long-term target; this file records what was agreed, what was found when
`plan.md` was checked against the code and database, and what is still open. When this file and `plan.md` disagree, this file wins.
The immediate goal is an independently operating **research** system (discover, test, reject, explain). Nothing here permits
autonomous live trading; that comes much later and behind the regulatory gate below.

## 1. Decisions

| # | Area | Decision |
|---|---|---|
| 1 | Universe | Start with the **historical Nifty 200** (point-in-time membership), not the 2,100+ stocks. Widen only when historical membership, delisted-stock coverage and instrument identity are reliable. |
| 2 | Holdout | **One globally locked holdout.** No discovery worker, researcher or LLM can read it. See section 3. |
| 3 | Compute | **One concurrent study worker.** Other experiments queue. Live ingestion first, then paper trading, then research. No separate worker pools yet. |
| 4 | Reuse | **Extend the existing studies, trials, verdict, holdout, trial counter, stage lifecycle, `backtest_run` and audit log.** No parallel `vti_*` tables, no second promotion state machine. Code stays under `algo`. |
| 5 | LLM | Optional and provider-isolated. Everything works without it. 250,000 tokens and Rs 1,000 a month, both enforced. Initial provider, if enabled: OpenAI. Never receives raw market data or holdout results. |
| 6 | Users | **Personal capital only** for v1. The shared Kite account stays protected: the system manages only positions attributable to its own recorded fills. |
| 7 | Timing | Phase 1 may run during the 8-week paper period, inside the limits in section 6. |

Non-negotiable rules:

1. **One source of truth.** The existing backtest engine, risk engine, lifecycle and OMS stay authoritative.
2. **No autonomous bypass.** An AI agent cannot promote a strategy, change a risk limit, read the holdout or place an unrestricted live order.
3. **Reproducibility.** Every experiment identifies its data snapshot, universe version, feature definitions, strategy definition, cost schedule and execution assumptions.

## 2. What `plan.md` assumed that the platform does not have

Checked on 2026-11-14 against the dev database and `pyproject.toml`.

| `plan.md` said | Found |
|---|---|
| 10 years of 1-minute data | True: `bar_1m` 2016-01-04 to 2026-11-13, about 336M rows. But no completeness check for minutes, and Kite's history is already vendor-adjusted. |
| 10 years of fundamentals | About 8: filing periods from 2018-03-31. Restatements, standalone vs consolidated and a reporting lag are not handled. |
| Sector, shareholding, promoter and institutional data | Not loaded. Only an `industry` field in the monthly constituent files. |
| DuckDB, Polars, scikit-learn, XGBoost, Optuna, statsmodels | None are dependencies. Add each only when a Phase needs it. |
| Existing Kafka | None. The ADR says Postgres only in v1. |
| Point-in-time universe | See section 4: much weaker than it reads. |
| New `vti_*` tables | Replaced by the mapping in section 5. |

## 3. The holdout

| Dataset | Dates | Purpose |
|---|---|---|
| Research / development | 2016-01-04 to 2024-12-31 | features, discovery, experiments, walk-forward |
| Global final holdout | 2025-01-01 to 2026-11-13 | one controlled final evaluation per frozen strategy family |
| Paper trading | from when the engineering gates pass | forward evidence |

Rules: (1) discovery and experiment workers cannot query holdout days; (2) the LLM never receives holdout data or detailed holdout
results; (3) a candidate must first pass development validation and walk-forward; (4) a frozen strategy family gets **one** final
evaluation; (5) detailed holdout results never flow back into discovery; (6) a failed family cannot be modified and retested
against the same holdout. The evaluator returns a controlled verdict, not a dataset. The trial counter spans the whole research
family and is never reset per study.

How it differs from what exists:

- Today the holdout is **per study** (`experiment.holdout_start/holdout_end`, one `study_holdout` row per study). All 8 registered
  studies use 2025-01-30 to 2026-11-11 and **none has been opened**, so no holdout has been consumed.
- Those studies' research windows run to 2025-01-29, which is 29 days inside the new global holdout. They must be re-registered
  with an end of 2024-12-31 (or clamped) before the lock is enforced.
- 2025-2026 prices are not pristine: the owner has seen charts and paper-run proposals on them. The lock stops the research loop
  from using them, it cannot make them unseen. Record this when the first family is evaluated.
- The lock must be enforced where data is read (a reader that refuses days on or after the holdout start), not by convention.

## 4. The Nifty 200 reality (a consequence of decision 1)

`docs/stage4/membership/MEMBERSHIP_COVERAGE.md` and the dev database show:

- Reconstructed membership covers **2020-10-01 to 2026-11-07** (1,513 sessions), not 2016. Release evidence goes back to 2017 and
  monthly snapshots to 2017-01..2022-03, but the loaded and reconciled window is the one above.
- **0 of 1,513 sessions are strict-eligible** (nothing is person-verified). 337 would be eligible once verified. The blockers are
  members with no instrument (PEL 831 sessions, GSPL 620, several demerger placeholders) and members not yet published on the
  decision day.
- `index_membership_event` and `index_membership_coverage` are **empty in the dev database**. The adopted revision 3 exists as
  CSV files under `docs/stage4/membership/`. Whatever the studies read as Nifty 200 today does not come from verified rows.

So until membership is verified and loaded, a Nifty 200 development window is about 2020-10 to 2024-12 (roughly 4 years, 1,050
sessions), not 2016 to 2024. **Open decision for the owner:** accept the shorter window, or also allow the AMFI market-cap
segment universe (lists from 2018-08, which the study runner uses today) as a clearly labelled second universe with its known
survivorship gap.

## 5. Mapping `plan.md` onto what exists

| `plan.md` concept | Existing piece to extend |
|---|---|
| Experiment, experiment run | `experiment` (study spec + SHA-256, holdout fields), `study_trial`, `study_run` |
| Validation engine, promotion review | `study_runner.run_verdict`, `validation_report`, `backtest/validation/*`, `config/validation_thresholds.json` |
| Trial counter, multiple-testing | `backtest/validation/registry.py` (migration 010): make it family-wide |
| Strategy registry, lifecycle statuses | `strategy_config`, `strategy_stage_change`, `strategy/stage.py` (see mapping below) |
| Strategy versions | immutable `strategy_config` rows plus params hash; add parent and reason fields only |
| Backtesting, costs, ledger | `backtest/engine.py`, `backtest_run`, `backtest_ledger`, cost schedules |
| Dataset versioning | `data_snapshot`, `snapshot_partition`, `DataAPI`, `data_freeze` |
| Audit | `portal_audit` |
| Scheduling | `algo/jobs` registry and runner, `job_run` |
| Risk, kill switch, OMS | `algo/risk`, `algo/execution` |
| Feature library | none yet. Closest: `data/ratios.py` (30 ratios), `screener` field catalog (17 ratio + 17 technical), `Context.fundamentals` |

Stage mapping: `plan.md` DISCOVERED and RESEARCH are research states inside the existing research stage; BACKTESTED and VALIDATION
are study outcomes (trials, verdict), not stages; APPROVED_FOR_PAPER, PAPER_TRADING, APPROVED_FOR_LIVE, ACTIVE use the existing
stage changes (the paper-stage waiver the owner recorded stays visible); DEGRADED, SUSPENDED, RETIRED are added only when
monitoring exists. No second state machine.

## 6. Resource limits

| Workload | Policy |
|---|---|
| Study workers | 1 at a time (today several may run, each about 2 GB: add a global limit) |
| Experiments | queued, no limit on the queue |
| Live ingestion | highest priority |
| Paper trading | above research |
| Feature generation | scheduled, resource-limited |
| Large discovery jobs | off-peak only |

Raise concurrency only after measuring CPU, memory, I/O and database contention.

## 7. Why the five validation reports failed

All five reports failed; none was close to a promotion. Gate results over the five (from `validation_report`):

| Gate | Failed | Of which "evidence missing" |
|---|---:|---:|
| beats_benchmark (Sharpe edge at least 0.2) | 5 | 0 |
| parameter_plateau | 5 | 4 |
| overfitting_probability | 5 | 4 |
| max_drawdown | 4 | 0 |
| oos_sharpe (at least 0.8) | 4 | 0 |
| deflated_sharpe (at least 0.95) | 4 | 0 |
| window_share | 3 | 0 |

Two findings. First, **no study beat its benchmark by the required margin** (edge from -0.66 to +0.03), which is a performance
result, not a technical one. Second, four of five reports had a single trial, so `parameter_plateau` and
`overfitting_probability` had no evidence to compute from: a one-trial study cannot pass those gates whatever it earns. Studies
meant to be validated need a parameter grid and several trials. The thresholds stay as they are; they are not loosened to get a
first promotion.

## 8. Regulatory gate (before Phase 6)

Not to be settled casually while building agents. It must establish the permitted scope of internal strategy generation,
automated decisions, automated order placement, use by other portal users and any later advisory or managed offering. An LLM
generating a strategy is not assumed to be treated like one the owner codes. The `regulatory_config` table is empty, so live is
blocked until the owner records the four rules.

## 9. Open items

1. Dev window: accept about 2020-10 to 2024-12 for the Nifty 200, or add the AMFI segment universe as a second labelled universe (section 4).
2. Verify and load the Nifty 200 membership (28 exceptions, PEL, GSPL, placeholders) so strict-eligible sessions exist.
3. Re-register the 8 studies against the 2024-12-31 research end and enforce the lock at the reader.
4. Frontend and portal work for research (queue view, holdout verdict display) is not specified yet.

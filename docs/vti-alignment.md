# VTI alignment: how `plan.md` fits the platform that exists

Decided by the owner on 2026-11-14. `plan.md` is the long-term target; this file records what was agreed, what was found when
`plan.md` was checked against the code and database, and what is still open. When this file and `plan.md` disagree, this file wins.
The immediate goal is an independently operating **research** system (discover, test, reject, explain). Nothing here permits
autonomous live trading; that comes much later and behind the regulatory gate below.

## 1. Decisions

| # | Area | Decision |
|---|---|---|
| 1 | Universe | **Nifty 200 only** for the first research dataset (point-in-time membership), not the 2,100+ stocks and not the AMFI universe. Widen only when historical membership, delisted-stock coverage and instrument identity are reliable. |
| 2 | Holdout | **One globally locked, frozen holdout (2025-01-01 to 2026-11-13), evaluated ONCE, by one preregistered batch for the whole research programme (every family together). It is consumed by that evaluation.** No discovery worker, researcher or LLM can read it. See section 3. |
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
| Global final holdout | **2025-01-01 to 2026-11-13, frozen** | **one** evaluation batch for the whole research programme, then consumed |
| Forward evidence | after 2026-11-13, and paper trading | never appended to the holdout; a larger holdout would need explicit evaluation vintages and its own access policy |

Rules: (1) discovery and experiment workers cannot query holdout days; (2) the LLM never receives holdout data or detailed holdout
results; (3) a candidate must first pass development validation and walk-forward; (4) candidates are frozen, then evaluated in
**one preregistered global batch** by a separate evaluator, with the multiple-testing correction applied across the whole batch and
each family's accumulated trial count; (5) the evaluator returns a controlled verdict, never metrics, equity curves or trades that could be
used to tune a candidate; (6) **the holdout is consumed globally when that batch is evaluated.** After it there is no second
evaluation against these dates and no further candidate submission against them, even for new candidates: repeated pass/fail
feedback is itself an optimisation signal. New strategies are judged on forward evidence after 2026-11-13. A later historical
evaluation needs a genuinely new, independently governed evaluation period.

**The holdout is global across families.** Independent research families do not each get their own evaluation: one holdout, one
batch, for the whole programme. The manifest lists **every** eligible candidate with its family id, each family's trial count, the
total number of candidates and the multiple-testing correction across all of them, and it is the complete frozen candidate set at
the evaluation cutoff.

**The batch manifest and its states.** Before any holdout data is read, the evaluator validates and freezes a manifest: batch id,
candidate ids and immutable strategy versions, parameter hashes, `dataset_sha256` and `study_sha256` for each, the development
validation reports, every candidate's family id and each family's trial count, the evaluation date range (it must equal the global
holdout), the multiple-testing procedure and version, and the evaluation code version. An accepted manifest is immutable. The
batch has a unique immutable id and moves only forward: `REGISTERED -> FROZEN -> EVALUATING -> CONSUMED`, or to the terminal
`EVALUATION_FAILED`, each transition atomic and audited.

**Invariant: at most one global holdout batch, ever.** The database enforces it (a uniqueness constraint over all batches). From
the moment a batch is `FROZEN`, no other batch can be registered, and this stays true if the evaluation is interrupted, fails or
remains `EVALUATING`. Recovery acts only on the original batch and its immutable manifest. The move to `EVALUATING` is atomic with
the durable record that holdout access has begun, and **the holdout counts as consumed from that moment**, whatever the outcome.
The evaluator rejects a modified manifest, a candidate not in the frozen manifest, a candidate without its required development
evidence, a second batch, and a resume with changed candidate definitions.

**Interrupted evaluation.** No partial candidate verdicts are ever exposed, and intermediate results stay inaccessible to
researchers and agents. Recovery uses the exact same manifest, evaluator version, data snapshot and statistical procedure, and
verdicts are committed atomically only after the whole batch finishes (`CONSUMED`). If deterministic recovery is impossible the
batch becomes `EVALUATION_FAILED`: the holdout stays consumed, no further attempt is allowed with modified inputs, and a crash can
never become a way to query the holdout again.

**Verdict values.** A candidate's gate and batch results are one of `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`, `NOT_APPLICABLE`.
Missing evidence is never a weak pass, and neither the platform nor a future research agent may read it as one. A candidate with
any `INSUFFICIENT_EVIDENCE` gate is not promotable. (Today missing evidence is reported as a failed gate with the text "evidence
missing"; the distinct state is part of the Phase 1 work.)

**Research family.** A family has a stable, immutable id. Every experiment that tests a hypothesis in the family adds to its
trial count. Re-registering a study, changing parameters, changing the feature set or splitting a study into several does **not**
create a new family or reset the count. A new family needs an explicit, audited classification decision (who, why, what makes the
hypothesis genuinely different), never an automatic result of registering a study.

Enforcement: the lock configuration is anchored in the database (a hash in an append-only table); if the file and the database
disagree every research reader fails closed; the unwrapped reader exists only behind an evaluator capability tied to a registered
batch. This stops accidents and ordinary code paths; it is not a defence against someone holding database credentials (a read-only
research database role limited to development-window views is a later hardening option).

How it differs from what exists:

- Today the holdout is **per study** (`experiment.holdout_start/holdout_end`, one `study_holdout` row per study). All 8 registered
  studies use 2025-01-30 to 2026-11-11 and **none has been opened**, so no holdout has been consumed. Opening per study is replaced
  by the batch evaluation above.
- Those studies' research windows run to 2025-01-29, 29 days inside the global holdout. The originals are **preserved** (their
  SHA-256, audit and trials stay); new registrations with a research end of 2024-12-31 supersede them, and the family's trial count
  carries forward.
- 2025-2026 prices are not pristine: the owner has seen charts and paper-run proposals on them. The lock stops the research loop
  from using them, it cannot make them unseen. Record this when the first batch is evaluated.

## 4. The Nifty 200 reality (a consequence of decision 1)

`docs/stage4/membership/MEMBERSHIP_COVERAGE.md` and the dev database show the following. Membership eligibility and price-adjustment eligibility are different questions and are reported separately.

**Membership** (`docs/stage4/membership/MEMBERSHIP_COVERAGE.md`, dev database):

- Reconstructed membership covers **2020-10-01 to 2026-11-07** (1,513 sessions), not 2016. Release evidence goes back to 2017 and
  monthly snapshots to 2017-01..2022-03, but the reconciled window is the one above.
- "0 of 1,513 strict-eligible" has two causes: (a) **verification**: all 1,513 sessions are PROVISIONAL, none person-verified;
  (b) **reconstruction**: only 356 sessions are COMPLETE (every member resolves to a tradable instrument with a bar), 1,157 are
  INCOMPLETE (members with no instrument: PEL 831 sessions, GSPL 620, demerger placeholders; members not yet published on the
  decision day). If verification were done now, 337 sessions would qualify.
- `index_membership_event` and `index_membership_coverage` are **empty in the dev database**; revision 3 exists as CSV files under
  `docs/stage4/membership/`.

**Price adjustment**: whether each member's price history has an unresolved corporate action. The earlier "167 of 200 strict-clean"
figure is superseded: on 2026-11-14 the review queue was closed under the Kite price source (0 open), valid for that series only;
after the NSE cutoff rights, demergers and buy-backs need a person again. Track it per member and date, not inside the membership
count.

**Decision (owner, 2026-11-14):** Nifty 200 only for the first research dataset; the AMFI market-cap universe is not a second
discovery universe in Phase 1.

**The development window is intended, not yet verified.** The intended initial window is 2020-10-01 to 2024-12-31. It becomes
eligible for Nifty 200 point-in-time research only after membership revision 3 has been person-verified, loaded into the database
and has passed the strict eligibility checks. Until then the platform may validate features against historical prices, but nothing
may claim point-in-time Nifty 200 universe validity, and **no Nifty 200 experiment may be registered**.

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
| Study workers | 1 at a time (today several may run, each about 2 GB). One advisory-lock "research slot" taken by every research entry point: study worker, trial runner, verdict and holdout evaluation, research backtest scripts, feature jobs, backfills. A static scan test enforces it |
| Experiments | queued, no limit on the queue |
| Live ingestion | highest priority |
| Paper trading | above research |
| Feature generation | scheduled, resource-limited |
| Large discovery jobs | off-peak only |

A lock serialises but does not yield: long jobs checkpoint (feature work monthly) and pause cleanly when paper trading, ingestion or the market-hours window needs the machine. Raise concurrency only after measuring CPU, memory, I/O and database contention.

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

1. Verify and load the Nifty 200 membership (the 13 documented exceptions, PEL, GSPL, placeholders) so strict-eligible sessions exist; report membership and price-adjustment eligibility separately. **Highest priority, alongside the holdout enforcement. No Nifty 200 experiment before it is done.**
2. Owner confirms the first feature formulas (`docs/vti-phase1-spec.md` section C) before they are implemented.
3. Register new versions of the 8 studies with a 2024-12-31 research end (originals untouched) under one family id carrying their trial counts, and enforce the lock at the reader.
4. Define the research family id and the audited classification procedure for a new family (section 3).
5. Add the distinct validation states `PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE` to gate results.
6. Holdout batch policy: one global batch across all families, at most one ever, consumed when `EVALUATING` is recorded; manifest, states, `EVALUATION_FAILED` and recovery as in section 3.
7. Data history: 336M minute bars are not proof of coverage; completeness reports by instrument, session and expected minute count before any intraday research.
8. Frontend and portal work for research (queue view, controlled holdout verdict display) is not specified yet.
9. Optional hardening: a read-only research database role limited to development-window views.

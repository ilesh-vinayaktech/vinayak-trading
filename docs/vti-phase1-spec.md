# VTI Phase 1: research foundation (specification, revision 2)

Scope, decisions and limits are in `docs/vti-alignment.md`; this file turns Phase 1 of `plan.md` into work items with acceptance
criteria and tests. Revision 2 (2026-11-14) incorporates the owner's review of revision 1: a stricter holdout, dataset identity
that pins input versions, immutable feature materialisations per dataset, price/volume features only, exact feature formulas, a
research slot on every entry point, and monthly checkpoints.

**Success metric.** Phase 1 succeeds when the platform can produce a historically correct, point-in-time, reproducible research
dataset and prove that the same inputs always give the same feature outputs. It does not succeed by finding a profitable strategy,
and it must not quietly become an alpha-discovery project.

Phase 1 may run during the paper period. It changes no live or paper behaviour, promotes nothing, raises no risk limit, writes to
no paper or live table, and runs nothing heavy while paper trading needs the machine.

Tests follow the project rule: written first, failing first, `make quick` while working, `make check` before a commit. New modules
under `src/algo/` need a matching `tests/**/test_<module>.py`. The 90% branch floor is a minimum, not proof of correctness: each
feature also has a hand-computed reference fixture and property tests as independent checks.

## 1. Prerequisites

| # | Prerequisite | Notes |
|---|---|---|
| P1 | Nifty 200 membership verified by a person and loaded (`index_membership_event`, declared `index_membership_coverage`); PEL, GSPL and the demerger placeholders resolved to instruments | Report two separate things, never one number (below) |
| P2 | **Decided:** Nifty 200 only for the first research dataset. No AMFI universe in Phase 1. The intended development window is 2020-10-01 to 2024-12-31, **eligible for point-in-time Nifty 200 research only after P1 is complete** (verified, loaded, strict checks passed) | Owner, 2026-11-14 |
| P3 | Register new versions of the 8 existing studies with a research end of 2024-12-31. **Never edit the originals** | See P3 below |

**P1: two eligibility questions, reported separately.**

- *Membership eligibility* (`MEMBERSHIP_COVERAGE.md`, 1,513 sessions 2020-10-01 to 2026-11-07): "0 strict-eligible" is the product of
  two causes. (a) Verification: all 1,513 are PROVISIONAL, so none is person-verified. (b) Reconstruction: only 356 sessions are
  COMPLETE (every member resolves to a tradable instrument with a bar); 1,157 are INCOMPLETE, mainly members with no instrument
  (PEL 831 sessions, GSPL 620, demerger placeholders) and members not yet published on the decision day (32 sessions are
  RETROSPECTIVE). If verification were done today, 337 sessions would qualify.
- *Price-adjustment eligibility*: whether each member's price history has no unresolved corporate action. The older figure "167 of
  200 strict-clean" in the TODO notes is superseded: on 2026-11-14 the review queue was closed under the Kite price source
  (0 items open), which holds only for that series. After the NSE cutoff, rights, demergers and buy-backs need a person again.
  Report this per member and per date, not folded into the membership count.

**P3: new registrations.** Preserve each original study, its SHA-256, its audit history and its trials. Register a new study
(`supersedes_experiment_id` records the link) with research end 2024-12-31. The strategy family and its **trial count carry
forward**: the multiple-testing penalty is not reset.

Until P1 is done, features may be computed and validated against historical prices (they do not depend on membership), but the
system cannot claim point-in-time Nifty 200 validity and **no Nifty 200 experiment may be registered**. Do not start Nifty 200
experiments until membership is strict-eligible.

## 2. Existing tables and modules to extend (before anything new)

| Need | Extend | How |
|---|---|---|
| Global holdout and lock | `experiment` (`holdout_*`), `study_holdout`, `research/study.py` validation, `scripts/study_worker.py` | Global lock anchored in the database (A). The per-study holdout open becomes a batch evaluation (A) |
| Data access that cannot see the holdout | `data/reader.py` `BarReader` | A guarded research reader; the unwrapped reader only through the evaluator capability |
| Family-wide trial counter | `backtest/validation/registry.py`, migration 010 | Add a family key; never reset per study or per re-registration |
| Dataset pin | `data_snapshot`, `snapshot_partition`, `DataAPI`, `data_freeze`, `experiment.study`, `study_sha256` | Add `dataset_sha256` and the feature pins to the study spec (B) |
| Research slot | `scripts/study_worker.py`, `research/study_jobs.py`, `research/study_runner.py`, every script that runs a backtest or verdict | One common resource guard (G) |
| Scheduling and history | `algo/jobs/registry.py`, `job_run` | The daily feature job is a registered job |
| Audit | `portal_audit` | Lock changes, evaluation batches, feature definition changes |
| Lifecycle | `strategy_config`, `strategy_stage_change` | No change in Phase 1 |

New tables only where nothing exists: `research_lock`, `holdout_batch` and its results (A), `feature_definition`, `feature_run`,
`feature_value` (C, F).

## 3. Work items

### A. Holdout lock and controlled evaluation

**Family.** A research family has a stable, immutable id; its trial count only grows. Re-registering, changing parameters or
features, or splitting a study never creates a family or resets the count; a new family needs an explicit, audited classification
decision (who, why, what makes the hypothesis genuinely different).

**Frozen window.** Development: 2016-01-04 to 2024-12-31. Global holdout: **2025-01-01 to 2026-11-13, fixed**. Observations after
2026-11-13 are forward-validation evidence, never appended to this holdout. A later, larger holdout would need explicit
evaluation vintages and a separate access policy; it is not part of Phase 1.

**Anchored in the database.** `research_lock` (append-only, migration 065): `config_sha256`, `development_end`, `holdout_start`,
`holdout_end`, `set_at`, `set_by`. `config/research_holdout.json` must hash to the newest row; if the file and the database
disagree, every research reader **fails closed**. Changing the lock is an audited, deliberate act and is refused once any batch
has been evaluated.

**Guarded reader.** `ResearchReader` wraps `BarReader` and refuses any bar, filing or feature value dated on or after
`holdout_start`. The unwrapped reader exists only behind an evaluator capability that `algo/research/evaluator.py` can obtain
solely for a registered, frozen batch. Honest limit: inside one Python process this stops accidents and ordinary code paths, not
someone with database credentials; the stronger boundary (research jobs connecting with a read role limited to development-window
views) is recorded as a hardening option, not a Phase 1 requirement.

**Evaluation is one global preregistered batch across all research families, and it consumes the holdout.** The database allows
at most one holdout batch ever (a uniqueness constraint over all batches): from `FROZEN` onward no other batch can be registered,
even if evaluation is interrupted, fails or stays `EVALUATING`.
1. Freeze each candidate (strategy config, parameters, `dataset_sha256`, `study_sha256`, development validation reports) before evaluation.
2. Register the batch: the frozen candidates, the family id and its trial count, the date range, the multiple-testing procedure and
   version and the evaluation code version. The evaluator validates this manifest **before reading any holdout data**; an accepted
   manifest is immutable and lists every candidate with its family id, each family's trial count, the candidate total and the
   correction across all of them. States move only forward and atomically, each audited:
   `REGISTERED -> FROZEN -> EVALUATING -> CONSUMED` or the terminal `EVALUATION_FAILED`. The move to `EVALUATING` is atomic with the
   durable record that holdout access began, and the holdout counts as consumed from then. An interrupted run stays `EVALUATING` and
   can only be re-run with the same manifest, evaluator version, data snapshot and statistical procedure; no partial verdicts are
   exposed and results are committed atomically at the end; if deterministic recovery is impossible the batch is `EVALUATION_FAILED`
   and no further attempt is allowed.
3. A separate evaluator runs the whole batch once; the correction is applied across the batch and the family's full trial count.
   When it completes the holdout is **consumed globally**: no second batch, no further candidate against these dates.
4. The result for research code is a **controlled verdict**: `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE` or `NOT_APPLICABLE` per
   candidate gate, with gate names. Missing evidence is never read as a weak pass. No metrics, equity curves, trades or dates. The detailed report is stored where only the owner reads it through the portal.
5. A failed candidate cannot be modified and resubmitted, and a new candidate cannot be evaluated against these dates once the
   batch is `CONSUMED`; new strategies use forward evidence after 2026-11-13.
6. Nothing from a verdict feeds discovery; the LLM never sees the holdout or its detailed results.

Acceptance:
1. No ordinary API, CLI or research process can return holdout data (history, issuer history, minute reader, fundamentals, feature reads).
2. Config file and database disagreeing, or a missing `research_lock` row, makes every research reader raise.
3. A study ending after 2024-12-31 is refused; 2024-12-31 is accepted; 2025-01-01 is refused.
4. The evaluator capability cannot be obtained without a `FROZEN` batch; a modified manifest, a candidate outside it, a candidate
   without development evidence, a second batch registered at any time after the first is `FROZEN` (including while `EVALUATING`
   or after `EVALUATION_FAILED`), or a re-run with a different manifest, evaluator version or snapshot is refused; no transition
   goes backwards; two concurrent registrations leave exactly one batch.
5. The research-facing result contains no figure beyond the four verdict values and gate names.
6. A lock change after a batch has run is refused; every lock change and batch is audited.

Tests: concurrent batch registration (two processes, one wins); a crash injected after partial holdout reads exposes no verdict and
resumes deterministically, or ends `EVALUATION_FAILED`; boundary-exact (2024-12-31 / 2025-01-01) on every reader entry point; file/DB mismatch fail-closed; capability tests
(forged token, reused token, unregistered batch); verdict redaction; a property test that no as-of or lookback argument reaches a
holdout date; existing holdout tests migrated to the batch path.

### B. Dataset identity and study manifest

Two hashes, kept separate:

- `dataset_sha256` identifies the **data inputs** only.
- `study_sha256` identifies the **complete study**: strategy and parameters, `dataset_sha256`, feature pins, cost and execution
  assumptions and the code commit.

`dataset_sha256` pins the versions actually read, not just a snapshot label:

| Component | Required identity |
|---|---|
| Data snapshot | Immutable snapshot id and its hash (`data_snapshot`) |
| Bar data | Provider, source and the `dataset_version` actually read per partition (from `snapshot_partition`) |
| Universe | Membership revision and the declared coverage (`index_membership_coverage`) |
| Prices | Price source and cutoff |
| Adjustments | Adjustment mode and `adjustment_version` |
| Window | Exact start and end dates |
| Costs | Cost schedule version(s) |

`study_sha256` additionally includes: feature ids, versions and definition hashes; strategy definition and parameters; the
execution assumptions (a versioned reference); the **git commit** and a `dirty` flag (a run from a dirty working tree is marked
non-reproducible and cannot support a holdout batch).

`dataset_sha256` resolves to an immutable dataset manifest stored append-only under that hash (snapshot, universe revision, price
source, adjustment mode and version, date range, cost schedule); `study_sha256` covers the strategy **implementation** (module
source hash and declared helpers), the feature definitions, the parameters and the code commit, not only the study specification.

Acceptance:
1. Same inputs give the same hashes in a fresh process; changing any single component changes the relevant hash.
2. A provider correction (a new `dataset_version`) creates a new `dataset_sha256` and leaves the old snapshot and its hash intact.
3. A study cannot be registered without both hashes; `SnapshotChanged` on verification refuses registration.
4. A dirty tree is recorded and blocks batch evaluation.

Tests: sensitivity per component; correction scenario (extends `test_snapshot.py`); dirty-tree flag; fresh-process equality.

### C. Feature registry (price and volume features only)

**Scope.** Phase 1 registers and materialises price/volume features only. The registry can describe fundamental features, but they
are stored with status `BLOCKED` and cannot be named in a study until the fundamentals prerequisites pass (reporting lag,
restatements, standalone vs consolidated; TODO 2.6). The screener's ratio fields are therefore not registered as usable.

**Tables** (migration 066 onward):

- `feature_definition(feature_id, name, version, status, manifest JSONB, manifest_sha256, created_at)`, unique `(name, version)`,
  append-only. `status` is `DRAFT`, `USABLE` or `BLOCKED` and moves only by new rows (a status history), never by update.
- `feature_run(run_id, feature_id, month DATE, dataset_sha256, code_commit, status, rows, result_sha256, started_at, finished_at, error)`
  with a unique constraint on `(feature_id, month, dataset_sha256)` for completed runs.
- `feature_value(run_id, instrument_id, day, value NUMERIC, available_at TIMESTAMPTZ)`, primary key `(run_id, instrument_id, day)`.

The same feature, instrument and day can therefore have several **immutable materialisations**, one per dataset. Nothing is
overwritten. A study reads features only through `read_features(dataset_sha256, pins)`, which finds the completed run for exactly
that dataset and **raises on a mismatch or a missing run; it never falls back** to another snapshot's values.

**The definition manifest** (canonical JSON, hashed) for each feature holds: formula identifier and parameters, input columns,
adjustment mode, window, warm-up, missing-data rule, availability rule, units and version. The implementation lives in one module
per feature family under `algo/features/`; shared helpers sit in `algo/features/_shared.py` and are declared as dependencies of
every feature that uses them. A feature's `manifest_sha256` covers the manifest, the module source and its declared
dependencies, and the run records the git commit. Editing any of them without a new version fails a test.

**Exact definitions for the first set** (proposed; the owner confirms or changes them before implementation). Common rules: all
price inputs are the **split/bonus point-in-time adjusted** series as of the feature day (`BarReader`, mode `split`, `as_of` = the
day's visible time), except traded value, which uses raw close and raw volume. A window that contains a missing session (no bar)
gives an absent value; nothing is interpolated or filled. A halted or suspended instrument has no bar and no value that day. Days
are sessions.

| Feature (v1) | Formula | Warm-up | Unit |
|---|---|---:|---|
| `ret_{5,20,60,120,252}d` | `close[t] / close[t-n] - 1` | n+1 closes | fraction |
| `vol_{20,60}d` | sample standard deviation (ddof = 1) of the last n daily simple returns `close[i]/close[i-1] - 1`, not annualised | n+1 closes | fraction |
| `atr_14d` | Wilder: `TR[t] = max(high-low, abs(high-close[t-1]), abs(low-close[t-1]))`; first value = mean of the first 14 TR, then `ATR[t] = (ATR[t-1]*13 + TR[t]) / 14` | 15 bars | price |
| `atr_pct_14d` | `atr_14d / close[t]` | 15 bars | fraction |
| `dist_sma_{50,200}d` | `close[t] / mean(close[t-n+1..t]) - 1` | n closes | fraction |
| `traded_value_20d` | mean over the last 20 sessions of `raw_close * raw_volume` | 20 bars | rupees |

`momentum` is `ret_*d`; no second definition exists. Anything not in this table is not a feature in Phase 1.

**Availability.** `available_at = max(available_at of every input observation)`, using the data layer's own visibility model
(`BarReader.visible_after` and the publish lag it is built with), not a constant in the feature code. A feature is never served
before it. (For later fundamental features the input time is the filing's knowledge time, not the period end.)

Acceptance:
1. Same feature and dataset reference give identical values and `result_sha256` across fresh processes.
2. A changed formula, manifest, module or declared helper without a version bump fails a test.
3. A value inside its warm-up, or with a missing session in its window, is absent, never zero.
4. `available_at` equals the maximum input availability for every row; no row is served earlier.
5. `read_features` raises for a dataset reference with no completed run and never substitutes.
6. A `DRAFT` or `BLOCKED` feature cannot be named in a study; fundamental features stay `BLOCKED`.
7. Sizing: about 200 members, about 1,050 sessions, about 15 features is under 3M rows for the development window; the load
   fits the daily job's limits.

Tests: one hand-computed reference fixture per feature (numbers worked out on paper); Hypothesis property: batch over a window
equals incremental one day at a time; availability rule; absence rules; version guard; mismatched dataset raises; status gating.

### D. Daily feature job and backfill

A registered job (after the evening data jobs and `paper-run`, off-peak) running `scripts/compute_features.py`, which materialises
only features whose validation status is `USABLE` (F).

**Checkpointing.** One `feature_run` per feature and calendar month, completed atomically (one transaction: rows and the run
marked `complete` with its hash). A failed month is recorded `failed` and invalidates nothing already complete. A restart or a
rerun processes only months that are incomplete or failed. Completed months are never rewritten.

**Yielding.** Between months the job checks whether higher-priority work needs the machine (`paper-run` or `paper-orders`
running, or the market-hours window with the live feed) and, if so, stops cleanly with status `paused`, to resume later.

Acceptance:
1. Re-running a completed month changes nothing and writes nothing.
2. Killing the job mid-month leaves no partial month; the next run redoes exactly that month.
3. A pause request takes effect at the next month boundary, with the completed months intact.
4. The job refuses (alerts) when `ReadinessService` says the input data is not ready.
5. It uses the guarded reader and never touches holdout days.
6. It writes only to the feature tables: no paper, live or lifecycle table (a test inspects every statement it issues).

Tests: idempotence, kill-and-resume, pause at the boundary, readiness refusal, holdout guard, write-set check.

### E. Point-in-time and look-ahead tests

Extend the look-ahead harness to features. For every registered feature, truncating the data at T must not change any value for
T or earlier. Specific scenarios, each its own test:

1. **Future corporate action.** Compute a feature for T; introduce a split or bonus announced and effective after T; recompute for
   T with point-in-time adjustment; the value is identical.
2. A late filing and a restated filing do not change a price feature (they are not inputs) and, once fundamental features exist,
   never change a value dated before their knowledge time.
3. A symbol or ISIN transition: the issuer-scoped history gives one continuous series; the instrument-scoped one does not mix ISINs.
4. A missing session gives an absent value and does not shift the window.
5. A halted instrument (no bars) gives no value.
6. A feature deliberately written with a look-ahead is shown to fail the harness.

The harness runs over the whole registry; a new feature that is not covered fails the registry test.

### F. Historical validation and reproducibility

`scripts/validate_features.py` produces, per feature and dataset, a report: coverage (share of eligible member-days with a value
after warm-up), absence by reason (warm-up, missing session, no bar), value ranges, an identical-recomputation check, and the
look-ahead result. A feature is set `USABLE` (a new status row, audited) only when coverage meets the owner-set minimum (default
90%), recomputation matches and the look-ahead tests pass.

Acceptance: recomputing a month from the same dataset gives the same `result_sha256`; a feature below the coverage minimum stays
`DRAFT`; the report is stored and referenced by the status change.

### G. Research slot (resource control)

One PostgreSQL advisory lock with a stable key, acquired through one resource-guard API (`algo/research/slot.py`), taken by **every**
research entry point: the study worker, the trial runner, verdict and holdout evaluation, `scripts/*` that run a backtest for
research, feature computation, historical backfills and validation. Build the guard alongside A and B and enforce it in D, so a
bypass is found early.

- A test lists the scripts and modules that call the backtest, study or feature APIs (static scan) and fails if any does not take
  the slot.
- A lock only serialises; it does not yield. Long jobs therefore checkpoint cooperatively (D) and honour a pause request.
- Research jobs run niced and do not start while `paper-run`, `paper-orders` or the live feed's market-hours window needs the
  machine.

Acceptance: two research jobs started together run one after the other; every entry point on the scan list takes the slot; a
request during market hours waits or pauses at the next checkpoint. The static scan is not the only proof: a multi-process test
launches every entry point concurrently and shows that only one runs at a time.

Tests: contention with fake jobs, the static scan, the market-hours guard on an injected clock, pause at a checkpoint.

### H. Documentation

`docs/features.md` (each feature: manifest, formula, warm-up, availability, version history) and `docs/research-dataset.md` (what the
two hashes pin and how to reproduce a run). A test fails when a registered feature has no entry.

## 4. Order of work

| Order | Work | Reason |
|---|---|---|
| 1 | P1 to P3 | Valid universe and research windows |
| 2 | A (lock, guarded reader, batch evaluation) and the slot API (G, core) | Nothing may read data before the lock exists; find bypasses early |
| 3 | B (dataset identity) | Reproducibility before anything is materialised |
| 4 | C (price feature registry) | Immutable feature contracts |
| 5 | E (look-ahead harness) | Prove correctness |
| 6 | F (validation) | Coverage and reproducibility |
| 7 | D (daily job) | Materialise only validated features |
| 8 | G (enforcement across all entry points) | Close every bypass |
| 9 | H | Kept current throughout |

## 5. Not in Phase 1

Alpha discovery, ML models, the strategy DSL, experiment generation, regime detection, the LLM gateway, intraday feature storage,
usable fundamental or sector features (need the fundamentals work in TODO 2.6 and a dated sector load), a second universe, a
growing holdout, and anything touching paper or live trading.

## 6. Additional acceptance criteria (cross-cutting)

| Area | Criterion |
|---|---|
| Holdout | No ordinary API, CLI or research process can access holdout data |
| Holdout | A holdout configuration changed outside the authorised process fails closed |
| Dataset | A historical provider correction creates a new dataset identity without changing the old snapshot |
| Features | Same feature and dataset reference give identical values across fresh processes |
| Features | Feature reads reject a mismatched dataset reference |
| Features | A feature cannot be used until its validation status is `USABLE` |
| Features | A future corporate action cannot change a past feature value |
| Fundamentals | Fundamental features stay unavailable until the point-in-time fundamentals prerequisites pass |
| Resource | Every research entry point takes the same research slot |
| Resource | Feature computation pauses at a monthly checkpoint for higher-priority work |
| Recovery | An interrupted job resumes without duplicating or modifying completed materialisations |
| Isolation | Feature computation cannot write to paper or live tables or change strategy lifecycle state |

## 7. Definition of done

`make check` green; every acceptance item has a test that failed first; each feature has a hand-computed fixture; a recorded feature
run reproduces byte-for-byte in a fresh process; the holdout lock is enforced in code, anchored in the database and tested at its
boundary; the research slot scan passes; `TODO.md` and `docs/vti-alignment.md` are updated.

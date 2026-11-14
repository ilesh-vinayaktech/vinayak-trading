# VTI Phase 1: research foundation (specification)

Scope, decisions and limits are in `docs/vti-alignment.md`; this file turns Phase 1 of `plan.md` into work items with acceptance
criteria and tests. Phase 1 may run during the paper period. It builds data and feature infrastructure only: it changes no live
or paper behaviour, promotes nothing, raises no risk limit and runs nothing heavy while paper trading needs the machine.

Tests follow the project rule: written first, failing first, `make quick` while working, `make check` before a commit. New modules
under `src/algo/` need a matching `tests/**/test_<module>.py`. Money-path floors are untouched; the feature code is not a money
path but is held to 90% branch.

## 1. Prerequisites (not Phase 1 work, but Phase 1 results are not trustworthy without them)

| # | Prerequisite | Why |
|---|---|---|
| P1 | Nifty 200 membership verified by a person and loaded (`index_membership_event`, declared `index_membership_coverage`); PEL, GSPL and the demerger placeholders resolved to instruments | Today 0 of 1,513 sessions are strict-eligible and the tables are empty (alignment section 4) |
| P2 | Decide the development window: Nifty 200 only (about 2020-10 to 2024-12) or also the AMFI segment universe as a labelled second universe | Decides how many years the first features and studies cover |
| P3 | Re-register the 8 existing studies with a research end of 2024-12-31 | Their research windows overlap the global holdout by 29 days |

Until P1 is done, features may be computed and validated (they do not depend on the membership), but no experiment may be
registered on a "Nifty 200" universe and called point-in-time.

## 2. Existing tables and modules to extend (before anything new)

| Need | Extend | How |
|---|---|---|
| Global holdout | `experiment` (`holdout_start`, `holdout_end`, `holdout_opened_at`), `study_holdout`, `research/study.py` validation | Keep the per-study one-time open. Add a global lock file `config/research_holdout.json` and refuse any study whose research window ends on or after its `holdout_start`, and any holdout window that starts before the global one |
| Data access that cannot see the holdout | `data/reader.py` `BarReader` | A guarded reader (see work item A) rather than a new data path |
| Family-wide trial counter | `backtest/validation/registry.py`, migration 010 | Add a `family` column to the trial counting, default the study's strategy family; never reset per study |
| Dataset pin | `data_snapshot`, `DataAPI`, `data_freeze`, `experiment.study` JSON and `study_sha256` | Add `dataset_ref` and `features` to the study spec, so they enter the SHA-256 |
| One study worker | `scripts/study_worker.py`, `research/study_jobs.py` (advisory locks per run) | Add one global advisory lock (the "research slot") every research job takes |
| Scheduling and history | `algo/jobs/registry.py`, `job_run` | The daily feature job is a registered job |
| Audit | `portal_audit` | Holdout lock changes and feature definition changes are audited |
| Lifecycle | `strategy_config`, `strategy_stage_change` | No change in Phase 1 |

New tables are justified only where nothing exists: a feature definition store, feature values, and a feature run record (work
items C and F). Everything else is an extension.

## 3. Work items

### A. Holdout lock

- `config/research_holdout.json`: `{"development_end": "2024-12-31", "holdout_start": "2025-01-01"}`. The holdout end is open
  (today's data keeps arriving inside the holdout).
- `algo/research/holdout_lock.py`: `ResearchReader` wraps `BarReader` and raises `HoldoutAccess` for any bar, fundamentals filing
  or feature value dated on or after `holdout_start`. Only the verdict and holdout evaluator receive an unwrapped reader.
- `research/study.py`: a study whose end is after `development_end` is refused with the reason.

Acceptance:
1. A research reader cannot return a bar dated 2025-01-01 or later, through history, issuer history or the minute reader.
2. A study registered with an end of 2025-01-02 is refused; one ending 2024-12-31 is accepted.
3. The holdout evaluator still opens the holdout once per study (existing tests unchanged).
4. Changing `config/research_holdout.json` is audited and is refused once any holdout has been opened.

Tests: boundary-exact (2024-12-31 allowed, 2025-01-01 refused), each reader entry point, the evaluator path, the audit row, a
property test that no date at or after the start can be reached by any lookback or as-of argument.

### B. Research dataset definition

A dataset reference is the tuple the alignment doc requires: data snapshot id, universe version (membership revision plus the
coverage declaration), price source and cutoff, adjustment mode, window, cost schedule version. `algo/research/dataset.py`
builds it and its SHA-256, and stores it in the study spec.

Acceptance:
1. The same inputs give the same hash; changing any one input changes it.
2. A study cannot be registered without a dataset reference; the reference is inside `study_sha256`.
3. A reference whose snapshot no longer verifies (`SnapshotChanged`) is refused.

Tests: hash stability and sensitivity per field, registration refusal, a changed bar under a pinned snapshot is detected.

### C. Feature registry (daily features only)

New tables (migration 065 onward, append-only like the other logs):

- `feature_definition(feature_id BIGSERIAL, name, version, kind, inputs JSONB, warmup_sessions, code_ref, definition_sha256, created_at)`,
  unique on `(name, version)`. A definition is never updated: a change is a new version.
- `feature_value(feature_id, instrument_id, day, value NUMERIC, available_at TIMESTAMPTZ, run_id)`, primary key
  `(feature_id, instrument_id, day)`. Rows are never updated; a recompute under the same version must equal what is stored.

`algo/features/` holds pure functions `compute(history_as_of, ...)` that take the same bounded history a strategy gets. First
set, reusing the code that exists rather than rewriting it: returns and momentum windows, volatility, ATR, distance from moving
averages, liquidity (traded value), and the screener's ratio fields from `data/ratios.py`. Intraday features are not stored; they
are computed on demand from bars until measurement says otherwise.

Acceptance:
1. Each feature has a version and a definition hash; editing the function body without a version bump fails a test (the hash
   of the code reference is checked against the stored definition).
2. `available_at` is the bar's visible time (close plus the publish lag) for price features and the filing time for ratio
   features; a value is never served before it.
3. A value inside its warm-up is absent, never zero.
4. Sizing check: 200 stocks, about 1,050 sessions, about 40 features is about 8M rows; the load completes inside the resource
   limits of the daily job.

Tests: version/hash guard, warm-up (absent not zero), `available_at` rules, hand-computed values for each first feature,
Hypothesis property: batch over a window equals incremental one day at a time.

### D. Daily feature job

A registered job (after the evening data jobs and `paper-run`, off-peak), `scripts/compute_features.py`: computes the newest
session's values for every registered feature and the Nifty 200 members of that day, resumable, and a `--from/--to` backfill that
processes one month at a time. It takes the research slot lock, runs niced, and yields to paper trading and ingestion (it never
starts while `paper-run` or `paper-orders` is running).

Acceptance:
1. Re-running a day changes nothing (same hash).
2. A stopped backfill resumes without recomputing finished months.
3. The job fails (alert) when its input data is not ready per `ReadinessService`, instead of computing from stale bars.
4. It never reads on or after the holdout start while in research mode (it uses the guarded reader), except for the explicit
   evaluation path, which is separate.

Tests: idempotence, resume, readiness refusal, lock contention with a study worker (only one runs), holdout guard.

### E. Point-in-time availability checks

Extend the look-ahead harness to features: truncating the data at day T must not change any value computed for T or earlier.

Acceptance: for every registered feature, over a fixture with a split, a bonus, a late filing and a restated filing, truncated and
full runs agree up to T; a filing dated after T never changes a ratio feature at T.

Tests: the harness run over the registry (a new feature without it fails the registry test), a feature deliberately written with
a look-ahead is shown to fail.

### F. Historical feature validation and reproducibility

`feature_run(run_id, feature_id, from_day, to_day, dataset_ref, rows, result_sha256, started_at, finished_at, status)` records each
computation. `scripts/validate_features.py` writes a per-feature report: coverage (share of member-days with a value), warm-up
behaviour, value ranges, share of absent values by reason, identical recomputation hash.

Acceptance:
1. Recomputing a range from the same dataset reference gives the same `result_sha256`.
2. A feature with coverage below an owner-set minimum (default 90% of eligible member-days after warm-up) is marked unusable and
   cannot be named in a study.
3. A study spec naming a feature version records the definition hash, so a changed definition is detected.

Tests: reproducibility over two runs, coverage refusal, study spec pinning.

### G. Resource limits

`research slot`: one advisory lock shared by the study worker and the feature jobs, so at most one research job runs. Research
jobs run niced and do not start in the market-hours window while the live feed and `paper-orders` run (09:00 to 15:55 IST).

Acceptance: two research jobs started together run one after the other; a research job requested during market hours waits.

Tests: lock contention with a fake job, the market-hours guard on an injected clock.

### H. Documentation

`docs/features.md` (each feature: definition, inputs, warm-up, availability rule, version history), `docs/research-dataset.md`
(what a dataset reference pins and how to reproduce a run). Kept current by a test that fails when a registered feature has no
entry.

## 4. Order of work

1. Prerequisites P1 to P3 (P1 needs the owner's verification; it can proceed in parallel with the rest).
2. A (holdout lock), because nothing else may read data before it exists.
3. B (dataset reference), then C (registry) and E (look-ahead harness) together.
4. F (validation and reproducibility), then D (the daily job), then G.
5. H as each item lands.

## 5. Not in Phase 1

Alpha discovery, ML models, the strategy DSL, the experiment queue beyond the research slot, regime detection, the LLM gateway,
intraday feature storage, new fundamentals handling (restatement, standalone vs consolidated: tracked in TODO 2.6 and needed
before fundamental features are used in discovery), sector features (needs a dated sector load), and anything touching paper or
live trading.

## 6. Definition of done

`make check` green; the acceptance items above each have a test that failed first; a recorded feature run reproduces
byte-for-byte; the holdout lock is enforced in code and tested at its boundary; `TODO.md` and `docs/vti-alignment.md` updated.

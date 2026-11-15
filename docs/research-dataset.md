# The research dataset: what the hashes pin and how to reproduce a run

Written 2026-11-15 from the code, not from the plan. Where the plan (`docs/vti-phase1-spec.md`) is ahead of the code, this says so.

## Two hashes, two questions

| Hash | Question | Where it lives | What it covers (as built) |
|---|---|---|---|
| `dataset_sha256` (a study) | Which DATA did this study read? | `study_dataset` (sealed by the study's first run; every later run recomputes it and stops with `DatasetChanged` on a difference) | price source (`kite`) and publish lag; `known_at`; the data freeze (id, through date, per-instrument checksums); the snapshot hash of the universe's instruments as the database held them at `known_at` (bars, corporate actions, review decisions); the universe spec and the membership intervals actually used; the window; the cost schedules in force |
| `study_sha256` | Which complete STUDY is this? | `experiment.study_sha256` (locked at registration) | the study document: spec and parameter grid, data freeze, cost schedules, `known_at`, and the code identity (git commit, dirty flag, strategy file hash) |
| `dataset_sha256` (a feature run) | Which data did this feature materialisation read? | `feature_run.dataset_sha256` | the freeze (id, through date, checksums of its items) and the snapshot hash of its instruments as of the freeze's `taken_at` |

Not yet built: feature pins inside `study_sha256` (a study cannot yet name features), and `read_features` is not yet wired into the study runner.
The two `dataset_sha256` values are different manifests of the same idea and are not interchangeable.

## What `known_at` does

A study's reader (`BarReader(known_at=...)`) sees only rows the database held at that moment: bars, corporate actions and review decisions ingested
later are invisible. A provider correction, a new corporate-action decision or a late membership event therefore cannot change an old study's
result; it produces a different `dataset_sha256` for a study registered afterwards. The feature job pins its reader to the freeze's `taken_at`
in the same way.

## The holdout

Everything above stops at the development end (2024-12-31). The lock (`research_lock`, `config/research_holdout.json`) is anchored in the database;
`ResearchReader` cannot return a holdout day; the feature store refuses a month that reaches the holdout; the one holdout batch is the only path that
reads it (`algo/research/holdout_evaluator.py`).

## Reproducing a study run

1. Check out the commit recorded in the study (`study.code.commit`); a study registered from a dirty tree is marked non-reproducible and cannot back a holdout batch.
2. Use the database that holds the study's freeze (`data_freeze` and `data_freeze_item`; `scripts/freeze_kite.py verify` names any frozen
   stock whose rows changed).
3. Run the study again (`study_worker.py`, which takes the research slot). The run recomputes `dataset_sha256` and compares it with the sealed one; a
   difference stops it before any result is written.
4. Compare the results; trials are deterministic given identical inputs (no clock, no randomness in `src/`).

## Reproducing a feature month

`scripts/compute_features.py --freeze <id>` materialises each USABLE feature month by month. A month already complete for the dataset is never rewritten;
`feature_run.result_sha256` is the hash of that month's rows (instrument, day, value, available_at), so recomputing the month from the same freeze must
give the same hash, which `scripts/validate_features.py` checks (independent reread) before a feature can become USABLE.

## Who may compute

Every research entry point (study worker, holdout evaluation, feature job, feature validation, conversion verification) holds the one research slot
(`algo/research/slot.py`), so only one runs at a time; the feature job also pauses at a month boundary for a paper run, paper orders or market hours.

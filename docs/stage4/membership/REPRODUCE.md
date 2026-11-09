# Reproducing the membership artifacts from a fresh clone (verified 2026-11-09 at c31a752)

Result: PASS. All 8 generated deliverables in this directory are byte-identical to the committed ones, and the only difference from
revision 3 (d17a1e9) is the intended two-line change in `membership_intervals.csv`.

## Procedure (as run)
1. `git clone` then `git checkout c31a752` (53ed989 is its ancestor, parent d17a1e9 = revision 3). No `data/`, no uncommitted file.
2. `uv sync --frozen` (lockfile; log: `reproducibility/fresh_clone_uv_sync_frozen.log`, exit 0).
3. `make check` in the clone, untruncated: `reproducibility/fresh_clone_make_check.log`: ruff clean (283 files formatted), mypy clean (98 files),
   **1310 passed**, coverage **100.00%** (6146 statements, 1750 branches, 0 missed, 0 partial), floors passed, exit 0.
4. Empty disposable `timescale/timescaledb:2.17.2-pg16`; `migrate()` from scratch: 25 migrations, no rows.
5. Identity master restored as INPUT from the verified production database (data-only: exchange, instrument, instrument_terms,
   instrument_alias, corporate_action_relationship; 2649/3098/2631/1 rows). It is not rebuilt from raw bars here.
6. From the raw lake (gitignored, copied; not in git) and committed config, with the documented scripts in this order:
   `load_current_lists`, `parse_index_releases`, `apply_transcriptions`, `apply_revocations`, `apply_placeholder_replacements`,
   `parse_monthly_snapshots` (each `--lake data/lake --db $URL`).
7. Negative control: reconstruct BEFORE recording the instruction: output equals revision 3 (1589 a member from 2020-10-01). The handover therefore
   depends on the persisted `security_conversion` row, not on config or a fixture.
8. `record_security_conversion.py --apply` (committed config); row identical to production in every field incl. evidence and relationship_id.
9. `reconstruct_nifty200_membership.py` (defaults): all 8 outputs byte-identical to c31a752; clone's `git status` clean afterwards.

## Input comparison with production (`reproducibility/input_fingerprints_*.txt`, rows the reconstruction reads)
Identical: anchor, current index lists, release documents, monthly snapshots, replacements, revocations, identity master.
**Not identical, and why:** 27 release rows and 114 monthly constituents for NESTLEIND dated before its alias started (2023-08-01) are stored in
production as UNMAPPED_SYMBOL (parsed before the identity migration) but map to instrument 2653 when parsed afterwards. The reconstruction output is
unaffected (the reviewed NESTLEIND equivalence and the same-issuer comparison make the two keys one issuer). Rebuild order is therefore a real input:
parse-before and parse-after the migration give different stored mappings but the same deliverables. Production also keeps older parser versions
(1-6) that the reconstruction never reads; the rebuild holds only the current ones.

## Not proven here
The instrument master and bars were not re-ingested from raw; the lake itself is not in git. This shows that committed code + config + lake +
identity master reproduce the committed membership, not that the identity master can be rebuilt from nothing.

# NESTLEIND migration: review pack (APPLIED 2026-11-09)

Instrument 1589 (NESTLEIND, ISIN INE239A01024) is split at the ISIN change of **2024-01-05** into an old-ISIN
instrument (INE239A01016) and itself. Code: `src/algo/data/identity_migration.py`; command:
`scripts/migrate_isin_change.py` (**dry run by default**); audit of the real dry run:
`nestleind_migration_dry_run.json`. The dry run executed every step and every check on the real data inside a
transaction that was rolled back (schema migrations included). Row counts, the alias, the migration list and the
absence of the 024 columns were identical before and after. Only the id sequence advanced (ids 2649 and 2650
were consumed by the two dry runs).

## What applying would do (from the real dry run)

| Table | Before (instrument 1589) | Old instrument gets | 1589 keeps |
|---|---|---|---|
| bars (`bar_1d`) | 811 | 107 (all dated before 2024-01-05) | 704 |
| corporate actions | 53 | 43 | 10 (the split of 2024-01-05 stays here) |
| action resolutions | 0 | 0 | 0 |
| terms | 1 (from 2023-08-01) | a copy valid 2023-08-01 to 2024-01-05 | valid from 2024-01-05 |

- New instrument (delisted, `delisted_on` 2024-01-05, `listed_on` NULL, `first_observed_on` 2010-01-08, `last_traded_on` 2024-01-04).
- Alias NESTLEIND: old instrument 2010-01-08 to 2024-01-05 (start `FIRST_OBSERVED`, end `EVIDENCED` by NSE circular CML60084);
  1589 from 2024-01-05 (`EVIDENCED`). No overlap at any moment.
- One `SAME_ISSUER_ISIN_CHANGE` relationship, old to new, effective 2024-01-05, last source session 2024-01-04, evidence and decision #15.
- Nothing is deleted or merged; rows are only re-pointed.

## The 14 checks (all passed on the real data; any failure rolls everything back)

For bars, corporate actions and resolutions: nothing lost or duplicated; the old instrument owns only rows before the change; the new one owns none
before it. Also: bars moved equal the bars dated before the change; terms inherited; and the **issuer-scoped read equals the read before in all three
adjustment modes** (closes, factors, volumes and adjustment version).

## What this migration does NOT do

1. It does not re-map release rows (3 unmapped component rows would map to the old ISIN once its alias exists) and it does not fix the membership
   intervals: the deliverable still shows 1589 as the member before the change. That is the separate handover correction.
2. It does not clean `listed_on` of instrument 1589 (2023-08-01, an archive boundary).
3. It adds no reverse script. **Take a database backup (at least the tables above) before `--apply`.**

## Consumer separation (done, tested): signals continuous, execution instrument-scoped

| Consumer | Identity now |
|---|---|
| Strategy signals (`DataAccess` in the backtest engine) | issuer-scoped (`issuer_load`): one continuous history across the ISIN change, every bar tagged with its owning instrument |
| Charts and indicators (`api/queries.py`) | issuer-scoped (`issuer_history`); the bars response carries `instrument_id` per bar so the transition is visible |
| Orders, fills, tradability, liquidity | instrument-scoped (`load`): a name is tradable only on days it has bars of its own |
| Ledger corporate-action entitlements | instrument-scoped (the held instrument's own actions) |
| Membership comparison | same-issuer equivalence for the comparison only |

`RunResult.signal_sources` records which instruments fed each name's signal. `adjustment_versions` now pins the prices the signal was computed on.
Regression backtest (`tests/integration/test_engine_identity.py`, 27 Dec 2023 to 9 Jan 2024, old ISIN to 4 Jan, new ISIN from 5 Jan, 10:1 split ex 5 Jan):
the decision at the 4 Jan close sees all 7 pre-change bars (owner = old ISIN) before the new ISIN has traded once; the first order on the new ISIN fills at
the 5 Jan open at the new ISIN's own raw open; no trade ever references the new ISIN before 5 Jan or the old ISIN at all; on 8 Jan the split adjustment has
become knowable and the closes of 4 and 5 Jan are on one scale. A backtest with no ISIN link is unchanged.

Point in time, stated plainly: the split's `knowledge_time` is the ex-date proxy (start of 5 Jan IST), so a decision on 4 Jan sees the pre-change closes unadjusted
(20,005 vs 2,002 raw). The real announcement was earlier (22 Dec 2023, NSE circular CML59895); using it would be a separate, evidenced change to `knowledge_time`.

Migration invariant added and tested: the migration refuses if any persisted backtest trade or ledger line dated before the change references the new instrument
(today: 0 trades, 0 ledger lines on instrument 1589).

Not yet modelled, so not claimed: a POSITION held across the change. The ledger has no explicit ISIN-change conversion (old position to new position at the
split ratio), so a position in the old ISIN would be stranded on 5 Jan. Today no strategy can hold the old ISIN (membership still names 1589), but the
membership handover correction must come with that ledger event.

## To authorise

1. Review this pack and the regression results above.
2. Take a backup, then run `uv run python scripts/migrate_isin_change.py --apply`.
3. Re-run `scripts/verify_nestleind_identity.py` (it will then be a real split, not an in-memory one), then the membership handover correction (with the ledger ISIN-change conversion) and the full `make check`.

## Applied: procedure, evidence and results (2026-11-09)

Authorised by the owner, subject to the pre-apply checklist. Every step below was done and checked.

| Step | Result |
|---|---|
| No writer active | no API, frontend or ingestion process running; the only session on the database was TimescaleDB's own scheduler |
| Backup | full custom-format dump `data/backups/algo_pre_nestleind_20261109T034307Z.dump` (82.6 MB, kept outside git), SHA-256 `cb9a10efad7cb665d715410ab6ed9674de86b6f2db3fc9f533843ad36d4b535d` |
| Backup restorable | restored into a disposable Timescale container (not the live server); all 10 key tables match production in row count AND content checksum (incl. 3,188,251 bars). One harmless error: pg_dump 18 writes `SET transaction_timeout`, unknown to server 16 |
| Target confirmed | database `algo`, instrument 1589, ISIN INE239A01024, old ISIN INE239A01016 absent, change 2024-01-05, one split ex 2024-01-05 |
| Final dry run | 14 of 14 checks; audit `data/backups/nestleind_final_dry_run.json`, SHA-256 `4c717182b69a8c762304212e546a4f76fc120409ac5904d323207e82bb0fe63b` |
| Apply | `scripts/migrate_isin_change.py --apply`, exit 0, 14 of 14 in-transaction checks; audit `nestleind_migration_applied.json` |
| Counts | old instrument **2653** (INE239A01016): 107 bars, 43 corporate actions, terms to 2024-01-05. Instrument 1589: 704 bars, 10 actions (the split stays), terms from 2024-01-05. 811 distinct sessions, 0 duplicates, 0 bars on 1589 before the change |
| Aliases / relationship | NESTLEIND: 2653 from 2010-01-08 (FIRST_OBSERVED) to 2024-01-05 (EVIDENCED); 1589 from 2024-01-05 (EVIDENCED). One SAME_ISSUER_ISIN_CHANGE 2653 to 1589, effective 2024-01-05, last source session 2024-01-04, decision 15. Migration 024 recorded |
| Baseline equality | `scripts/verify_issuer_baseline.py` against a second restore of the backup: issuer series identical (bars, closes, factors, volumes, adjustment version) in none, split and total_return, read via either ISIN; instrument reads separate (704 / 107). Report: `nestleind_post_apply_baseline_check.md` |
| `make check` | green: 1275 passed, 100% coverage |
| Readiness | `scripts/stage4_readiness.py` re-run: unchanged blockers U1, U2, C1, K1, V1, R1; strict run still not possible. Output in `docs/stage4/readiness.json` |

`scripts/verify_nestleind_identity.py` was written for the pre-migration state (it splits 1589 in memory); after the real split it would only compare 1589 with
itself, so the baseline comparison above is the post-apply verification. The id sequence advanced past the ids used by the dry runs (the old instrument is 2653).

**Rollback, if a later problem is traced to this migration:** stop all research workflows on the data and restore from the backup above; do not improvise a reverse
migration. Still required before the membership handover: the ledger ISIN-change conversion (quantity, cost basis, realised/unrealised P&L, provenance).

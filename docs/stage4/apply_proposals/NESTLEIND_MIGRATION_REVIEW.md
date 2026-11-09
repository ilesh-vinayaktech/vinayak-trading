# NESTLEIND migration: review pack (NOT applied)

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

## Open decision before anyone applies it: consumers still use the instrument-scoped read

After the split, `BarReader.history` / `load` return only an instrument's own bars. These callers would therefore lose NESTLEIND's pre-2024 history:
`backtest/engine.py:196` (`reader.load`), `api/queries.py:206` and `:373` (charts), and, through the engine, `strategy/context.py:43`.
Switching them to `issuer_load` / `issuer_history` keeps signals and charts continuous, but it is a decision about simulation: orders are keyed by
instrument, so a fill before 2024-01-05 would be priced from the old ISIN's bars for the new instrument id. I have not changed these callers.

## To authorise

1. Decide the consumer question above (switch signals and charts to the issuer read, keep execution instrument-scoped).
2. Take a backup, then run `uv run python scripts/migrate_isin_change.py --apply`.
3. Re-run `scripts/verify_nestleind_identity.py` (it will then be a real split, not an in-memory one) and the full `make check`.

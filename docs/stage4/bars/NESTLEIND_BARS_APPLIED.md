# NESTLEIND (instrument 2653, INE239A01016) historical bars LOADED (owner-approved, 2026-11-10)

Source: the NSE bhavcopy files already stored in the lake (never fetched), loaded under each partition's own dataset version (1, source nse, series EQ).
Identity tables, aliases, the verified conversion, corporate actions, the membership deliverables and every other instrument's bars were not touched.

| Control | Result |
|---|---|
| Reconciliation before the write | 809 member sessions expected; 107 with bars, 702 without; 1,001 stored raw files in 2019-10-01..2023-07-31, 49 exchange-holiday files (hold the previous day, skipped as the loader always does), 952 sessions with a NESTLEIND EQ row. The "2 members missing bars" in the readiness report counted distinct instruments (2653 and JSWENERGY 1179), the 702 counted sessions |
| Why eligibility stayed at 337 | every one of the 702 sessions is also blocked by another member: PEL 649, GSPL 620, JIOFIN 21 (listed in `nestleind_2653_bars_dry_run.md`), so bars alone free no session |
| Writers | none (TimescaleDB's scheduler only; 0 client sessions at apply) |
| Backup | `data/backups/algo_pre_nestleind_bars_20261110T020104Z.dump`, SHA-256 `293b15a67d008cf8e462914b4dc6b839cfbc7f6a086f919f341c029ae5f64de5` |
| Restore test | disposable Timescale container: 11 table fingerprints identical to production, 0 errors |
| Final dry run | rolled back; manifest SHA-256 `e1ccc1a41bafb26775fcfaabd7e512125d886a6594252e6aa0b314a373607388`; all fingerprints unchanged afterwards. Reports: dry_run.md sha256 `7c896d01...`, dry_run.json sha256 `b2ad71cc...` |
| Apply | 952 rows inserted (702 member sessions + 250 warm-up sessions from 2019-10-01 for the 252-day lookback); same manifest SHA-256 |
| Fingerprints, before vs after | only bar_1d for 2653 (107 -> 1,059 rows) and partition_load (+952 audit rows) differ; bar_1d for every other instrument, instrument, instrument_alias, instrument_terms, relationship, security_conversion, corporate_action, action_resolution, review_decision identical |
| The original 107 bars | content hash identical to before |
| New bars vs raw | 952/952 raw-file SHA-256 equal to the manifest (latest stored version used; 2021-11-04 has a provider correction v0002); 951 CSV rows equal the stored file field by field; the one Excel-format file (2022-08-08) is checked by continuity |
| Series integrity | 1,059 bars; previous-close chain unbroken across all of them (including the 2023-07-31 -> 2023-08-01 join: 22,553.30 -> 22,593.70); largest daily move 12.8%, none over 25%; instrument 1589 still has 704 bars from 2024-01-05 |
| Audit trail | 952 partition_load rows (status noop, detail.kind = instrument_backfill, the raw SHA-256 and row count of each day) |

Rollback, if ever needed: restore the backup above, or delete exactly the rows with `instrument_id=2653 AND ts < 2023-08-01` and the 952 audit rows whose detail.kind is instrument_backfill.
Readiness was recomputed: sessions where 2653 is a member now have bars, so the "no bar 2653" blocker is gone from U2; eligibility is unchanged until PEL/GSPL are mapped.

# Six exchange-derived demerger factors: RECORDED as PROVISIONAL (owner-approved, 2026-11-09)

| Step | Result |
|---|---|
| No writer active | only TimescaleDB's background scheduler on the database; no API, frontend or ingestion process |
| Backup | `data/backups/algo_pre_demerger_resolutions_20261109T171755Z.dump` (86.6 MB, outside git), SHA-256 `67a97df61e38d3d51dc2514f7ad9f98356ffbe7906a0f6844c31c23a99cff0b5` |
| Backup restorable | restored into a disposable Timescale container (not the live server): action_resolution, corporate_action, instrument, security_conversion, review_decision, schema_migration and all 3,188,251 bars identical in count and content checksum |
| Final dry run on the exact production database | 67/67 PASS, rolled back, action_resolution unchanged (36 rows); report sha256 `4a76a93dabeb1135ef21ab13fd3ecb8c2aa1e7469104af85cdc50f13bc112a47` |
| Apply | `scripts/record_action_resolutions.py --apply`, exit 0, 67/67 in-transaction checks; 36 -> 42 rows (ids 55-60; ids 37-54 were consumed by rolled-back dry runs) |
| Post-apply (read-only) | the latest resolution of each of the six is `exchange_adjusted_price`, provisional, factor = base / previous close at full precision, bhavcopy SHA-256 and dated reports stored, no official source claimed; each earlier gap estimate kept as history and superseded. The four older demergers are untouched (gap, provisional) |
| Readiness | C1 evidence: PROVISIONAL_EXCHANGE_DERIVED 6, PROVISIONAL_GAP_ESTIMATE 4, NO_ADJUSTMENT_VERIFIED 24, IGNORED_WITH_REASON 2, UNRESOLVED 100. Blockers unchanged (U1, U2, C1, K1, V1, R1) |

Not verified. Promote to VERIFIED only after the original NSE/BSE circular confirms, for each: (1) the special pre-open session applied to that
security and date, (2) the official adjusted base price equals the bhavcopy observation, (3) the entitlement ratio and terms match the recorded
action, (4) the factor uses the correct previous cum-entitlement close. Strict mode keeps withholding these names while a lookback crosses the
ex-date (STRICT_WINDOWS.md). Rollback, if ever needed: restore the backup above; do not delete rows (the table is append-only by design).

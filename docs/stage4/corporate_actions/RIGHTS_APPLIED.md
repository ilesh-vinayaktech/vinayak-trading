# Nine rights issues: RECORDED as PROVISIONAL_ISSUER_TERMS (owner-approved, 2026-11-09); SUZLON held

| Step | Result |
|---|---|
| Backup | `data/backups/algo_pre_rights_resolutions_20261109T180017Z.dump`, SHA-256 `c84a145ca57a1073458b32deed3af741952e2999a369952875b9dd8984e38b78` (outside git) |
| Restore test | disposable Timescale container (not the live server): 7 key tables incl. 3,188,251 bars identical in count and content checksum, 0 restore errors |
| Final dry run, exact production database | 100/100 PASS, rolled back, action_resolution unchanged (42 rows); audit report SHA-256 `afbb51c11817258b7e5699523129bcda76e083fe0b6d1aefb6d97750f2e070d2` |
| Records and classes confirmed | exactly nine: RELIANCE, SHRIRAMFIN, LTF, BHARTIARTL, INDHOTEL, GRASIM, TATACONSUM, UPL, ADANIENT; each PROVISIONAL_ISSUER_TERMS |
| Writers | none (only TimescaleDB's scheduler; 0 client sessions at apply) |
| Apply | 100/100 in-transaction checks; 42 -> 51 rows (ids 76-84) |
| Post-apply, read-only | every row: method rights, provisional, factor = TERP/P at full precision, A/B/S/P stored as inputs, bhavcopy and issuer-document SHA-256 stored, no source_url and no confirmer (not verified). UPL and TATACONSUM carry their conflict verbatim (both values, status UNRESOLVED). ADANIENT and UPL state the FAQ limitation. SUZLON: no resolution |
| No accidental verification | statuses before: ignored 2, no_adjustment_verified 24, provisional 16; after: ignored 2, no_adjustment_verified 24, provisional 25 |
| Readiness | C1 by evidence: EXCHANGE_DERIVED 6, ISSUER_TERMS 9, GAP_ESTIMATE 4, NO_ADJUSTMENT_VERIFIED 24, IGNORED 2, UNRESOLVED 91. Blockers unchanged |

Strict mode is unchanged by this write: every one of these is provisional, so the reader still treats the action as unresolved (checked per row in the
apply) and the engine withholds the name while a lookback crosses its ex-date. Research mode applies the factor and lists it as provisional.

Open: UPL (NSE circular 149/2024 reports 0.959510 against our 0.959243) and TATACONSUM (exchange example cum price 1231.25 against the bhavcopy
1223.60) need the original exchange circulars; SUZLON needs its letter of offer. Rollback, if ever needed: restore the backup above.

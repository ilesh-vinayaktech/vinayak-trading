# Benchmark Release 1.1 - change report against 1.0

Release 1.0 (tag `benchmark-release-1.0`) is untouched and still verifies. 1.1 changes **evidence**,
not datasets.

| item | 1.0 | 1.1 |
|---|---|---|
| benchmark dataset hashes (4 series) | see 1.0 | **identical** |
| validation records | 6, 7, 8 (+4 net) | **identical** |
| 2022-08-08 bhavcopy | quarantined (spreadsheet served as CSV) | recovered, verified, loaded (1,710 bars); U01 RESOLVED |
| instrument-level blocked dates | 2022-08-08 | none |
| the 22 benchmark-only sessions | existence evidenced only by the benchmark | existence confirmed by NSE's own legacy bhavcopy (TIMESTAMP + PREVCLOSE chain 100%) |
| session kinds / hours | UNCONFIRMED / UNKNOWN | **unchanged** (no NSE circular found); two secondary broker claims recorded, not promoted |
| session outcomes | 1,752 confirmed regular, 10 confirmed special, 5,020 weekday-rule provisional, 22 benchmark-only, 1 quarantined | 1,753 confirmed regular, 32 confirmed special, 5,020 weekday-rule provisional |
| eligibility (daily / intraday / gate) | yes / no / no for all four | **unchanged** |

Why eligibility did not change: intraday research stays blocked by U02 (historical hours unverified) and
U03 (kinds and hours of special sessions unconfirmed); the gate stays blocked by every unresolved
finding. Open: U02-U06, U08-U11, U16. U12 (legacy validations) was closed in 1.0.

Provenance of the new evidence: `docs/recovery/bhavcopy_2022-08-08.json`,
`docs/recovery/incident_b0a7e50.json`, `docs/session-evidence/legacy_bhavcopy_check.json`,
`config/session_secondary_evidence.json`; audit outputs in `docs/benchmark-audit-1.1/`.

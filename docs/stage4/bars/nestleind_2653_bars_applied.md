# NESTLEIND (instrument 2653, INE239A01016) bar load: APPLIED

Window 2019-10-01..2023-07-31. Source: stored NSE bhavcopy files only (never fetched). Manifest SHA-256 `e1ccc1a41bafb26775fcfaabd7e512125d886a6594252e6aa0b314a373607388`; per-day detail and every raw file's SHA-256: `nestleind_2653_bars_applied.json`.

| item | value |
|---|---|
| member sessions expected by the membership deliverable (2020-10-01..) | 809 |
| stored raw files in the window / holiday files (hold the previous day) / sessions with a row for the alias / rows | 1001 / 49 / 952 / 952 |
| bars before the load | 107 |
| rows the load inserts | 952 (days by status: {'loaded': 952, 'partition_not_loaded': 49}) |
| bars after (inside the transaction) / persisted right now | 1059 / 1059 |
| expected member sessions with a bar: before -> after | 107 -> 809 |
| expected member sessions still without a bar | 0 |
| price continuity: largest |daily return| after / sessions over 25% | 0.128 / 0 |
| sessions eligible once verified: before -> after (newly eligible) | 337 -> 337 (0) |

Why the eligible count moves (or not): the sessions where this instrument is a member that are still not eligible once verified, and what blocks them:

| remaining blocker | sessions |
|---|---|
| s:PEL | 649 |
| s:GSPL | 620 |
| s:JIOFIN | 21 |
| RETROSPECTIVE i:1154 | 11 |
| RETROSPECTIVE s:JIOFIN | 11 |
| no bar i:1179 | 1 |

The membership intervals, identity tables and every other instrument's bars are untouched by this operation (verified by the caller's fingerprints).

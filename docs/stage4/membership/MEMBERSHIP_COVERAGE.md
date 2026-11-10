# Nifty 200 membership coverage per trading session (read-only)

Window 2020-10-01..2026-11-07: 1513 trading sessions with bars (2020-10-01..2026-11-06). Independent official N200 / Midcap 100 monthly snapshots end 2022-03-31.
Verification status: PROVISIONAL: nothing here is person-verified, and no coverage has been declared in index_membership_coverage

## Two separate questions

| Axis | What it answers | Sessions |
|---|---|---|
| Reconstruction completeness | every member a tradable instrument with a bar that session | COMPLETE 356, INCOMPLETE 1157 |
| Point-in-time knowledge | every member's state already published by that day's decision | CONTEMPORANEOUS 1481, RETROSPECTIVE 32 |
| Independent check | an official snapshot series covers the session (quality; does not block) | CHECKPOINTED 372, RELEASE_ONLY 1141 |
| Verification | person-verified | {'PROVISIONAL': 1513} |

**Strict-eligible sessions: 0 of 1513.** Eligible once verified (complete and contemporaneous): 337 of 1513.

## Why sessions are not eligible once verified (entity: sessions affected)

| reason | sessions |
|---|---|
| member without an instrument: s:PEL | 831 |
| member without an instrument: s:GSPL | 620 |
| member without an instrument: p:DUMMYSIEMS | 49 |
| member without an instrument: p:DUMMYHDLVR | 49 |
| member without an instrument: p:DUMMYVEDL1 | 30 |
| member without an instrument: p:DUMMYVEDL2 | 30 |
| member without an instrument: p:DUMMYVEDL3 | 30 |
| member without an instrument: p:DUMMYVEDL4 | 30 |
| member without an instrument: p:DUMMYABFRL | 22 |
| member without an instrument: s:JIOFIN | 21 |
| member without an instrument: p:DUMMYTATAM | 19 |
| member without an instrument: p:DUMMYITC | 17 |
| not yet published at the decision: i:1154 | 11 |
| not yet published at the decision: s:JIOFIN | 11 |
| not yet published at the decision: i:1118 | 7 |
| not yet published at the decision: p:DUMMYITC | 7 |
| not yet published at the decision: i:2550 | 5 |
| not yet published at the decision: p:DUMMYVEDL3 | 5 |
| not yet published at the decision: i:707 | 4 |
| not yet published at the decision: p:DUMMYSIEMS | 4 |
| not yet published at the decision: i:1308 | 4 |
| not yet published at the decision: p:DUMMYHDLVR | 4 |
| not yet published at the decision: i:2480 | 4 |
| not yet published at the decision: p:DUMMYVEDL1 | 4 |
| not yet published at the decision: i:34 | 2 |
| not yet published at the decision: p:DUMMYABFRL | 2 |
| not yet published at the decision: i:2492 | 2 |
| not yet published at the decision: i:2536 | 2 |
| not yet published at the decision: p:DUMMYVEDL2 | 2 |
| not yet published at the decision: p:DUMMYVEDL4 | 2 |
| member without a bar: i:1179 | 1 |
| not yet published at the decision: i:2379 | 1 |
| not yet published at the decision: p:DUMMYTATAM | 1 |

## Contiguous runs that would be eligible once verified

| from | to | sessions |
|---|---|---|
| 2024-09-30 | 2025-01-03 | 66 |
| 2025-02-06 | 2025-04-04 | 39 |
| 2025-06-25 | 2025-10-13 | 76 |
| 2025-11-13 | 2025-12-04 | 16 |
| 2026-02-20 | 2026-04-29 | 44 |
| 2026-06-22 | 2026-11-06 | 96 |

Per-session detail and the SHA-256 of each day's member set: `membership_sessions.csv`. A release dated d counts as known at d's close.

# Candidate vs frozen membership deliverables

Generated 2026-11-09. The frozen files in `docs/stage4/membership/` are UNCHANGED. This folder is a
candidate built with parser v7, six reviewed revocations/supplements, four reviewed placeholder
replacements and one reviewed entity equivalence. Adopt only after review.

## membership_events: frozen 242 rows, candidate 258 rows

- ADDED   `2023-07-20 | JIOFIN | ADD | pr_ind_prs17072023 | N50/Nifty 50/p1`
- ADDED   `2023-08-21 | JIOFIN | ADD | pr_ind_prs05092023 | N50/placeholder replacement/p1`
- ADDED   `2023-08-21 | JIOFIN | REMOVE | pr_ind_prs05092023 | N50/placeholder replacement/p1`
- ADDED   `2024-03-28 | BSE | ADD | pr_ind_prs19032024 | MID100/Nifty Midcap 100/p1`
- ADDED   `2025-01-06 | DUMMYITC | ADD | pr_ind_prs30122024 | N50/Nifty 50/p1`
- ADDED   `2025-01-29 | DUMMYITC | REMOVE | pr_ind_prs06022025_1 | N50/placeholder replacement/p1`
- ADDED   `2025-01-29 | ITCHOTELS | ADD | pr_ind_prs06022025_1 | N50/placeholder replacement/p1`
- ADDED   `2025-02-10 | ITCHOTELS | REMOVE | pr_ind_prs06022025_1 | N50/Nifty 50/p1`
- ADDED   `2025-10-14 | DUMMYTATAM | ADD | pr_ind_prs07102025 | N50/Nifty 50/p1`
- ADDED   `2025-11-12 | DUMMYTATAM | REMOVE | pr_ind_prs13112025 | N50/placeholder replacement/p1`
- ADDED   `2025-11-12 | TMCV | ADD | pr_ind_prs13112025 | N50/placeholder replacement/p1`
- ADDED   `2025-11-17 | TMCV | REMOVE | pr_ind_prs13112025 | N50/Nifty 50/p1`
- ADDED   `2025-12-05 | DUMMYHDLVR | ADD | pr_ind_prs28112025 | N50/Nifty 50/p1`
- ADDED   `2026-02-16 | DUMMYHDLVR | REMOVE | pr_ind_prs20022026_1 | N50/placeholder replacement/p1`
- ADDED   `2026-02-16 | KWIL | ADD | pr_ind_prs20022026_1 | N50/placeholder replacement/p1`
- ADDED   `2026-02-24 | KWIL | REMOVE | pr_ind_prs20022026_1 | N50/Nifty 50/p1`

## membership_intervals: frozen 322 rows, candidate 329 rows

- ADDED   `i:1118 | ITCHOTELS | 1118 | True | INSTRUMENT | 2025-01-29 | 2025-02-10 | EVENT`
- ADDED   `i:1154 | JIOFIN | 1154 | True | INSTRUMENT | 2023-08-21 | 2023-09-07 | EVENT`
- ADDED   `i:1308 | KWIL | 1308 | True | INSTRUMENT | 2026-02-16 | 2026-02-24 | EVENT`
- ADDED   `i:2379 | TMCV | 2379 | True | INSTRUMENT | 2025-11-12 | 2025-11-17 | EVENT`
- ADDED   `i:417 | BSE | 417 | True | INSTRUMENT | 2024-03-28 |  | EVENT`
- ADDED   `p:DUMMYHDLVR | DUMMYHDLVR |  | False | PLACEHOLDER | 2025-12-05 | 2026-02-16 | EVENT`
- ADDED   `p:DUMMYITC | DUMMYITC |  | False | PLACEHOLDER | 2025-01-06 | 2025-01-29 | EVENT`
- ADDED   `p:DUMMYTATAM | DUMMYTATAM |  | False | PLACEHOLDER | 2025-10-14 | 2025-11-12 | EVENT`
- ADDED   `s:JIOFIN | JIOFIN |  | False | UNMAPPED_SYMBOL | 2023-07-20 | 2023-08-21 | EVENT`
- REMOVED `i:1154 | JIOFIN | 1154 | True | INSTRUMENT | 2020-10-01 | 2023-09-07 | WINDOW_START_BACKWARD_WALK`
- REMOVED `i:417 | BSE | 417 | True | INSTRUMENT | 2020-10-01 |  | WINDOW_START_BACKWARD_WALK`

## membership_exceptions: frozen 21 rows, candidate 12 rows

- ADDED   `MEMBER_WITHOUT_INSTRUMENT | s:JIOFIN | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYHDLVR | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYITC | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYTATAM | N200`
- REMOVED `SNAPSHOT_MISMATCH_BLOCK | i:1118 | N200`
- REMOVED `SNAPSHOT_MISMATCH_BLOCK | i:1154 | N200`
- REMOVED `SNAPSHOT_MISMATCH_BLOCK | i:1589 | N200`
- REMOVED `SNAPSHOT_MISMATCH_BLOCK | i:417 | N200`
- REMOVED `SNAPSHOT_MISMATCH_BLOCK | s:NESTLEIND | N200`
- REMOVED `WALK_EXCLUDED_BUT_MEMBER_AFTER | i:1020 | MID100`
- REMOVED `WALK_EXCLUDED_BUT_MEMBER_AFTER | i:1020 | N200x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:1108 | MID100`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:1108 | N200x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:2647 | N100x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:2647 | N200x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:460 | MID100`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | i:460 | N200x`

## membership_cancellations (new file): 6 cancelled announced changes

- 2024-03-28 IREDA MID100 INCLUDED (announced in pr_ind_prs28022024) revoked by pr_ind_prs19032024
- 2024-03-28 IREDA N200x INCLUDED (announced in pr_ind_prs28022024) revoked by pr_ind_prs19032024
- 2024-09-30 CENTRALBK MID100 INCLUDED (announced in pr_ind_prs23082024) revoked by pr_ind_prs25092024
- 2024-09-30 CENTRALBK N200x INCLUDED (announced in pr_ind_prs23082024) revoked by pr_ind_prs25092024
- 2024-09-30 IDEA MID100 EXCLUDED (announced in pr_ind_prs23082024) revoked by pr_ind_prs25092024
- 2024-09-30 IDEA N200x EXCLUDED (announced in pr_ind_prs23082024) revoked by pr_ind_prs25092024

## membership_entity_equivalence (new file)

- s:NESTLEIND -> i:1589 (NESTLEIND); review decisions 15;26

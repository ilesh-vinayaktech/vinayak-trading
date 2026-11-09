# Revision 3 candidate vs adopted revision 2

Adds: the DUMMYSIEMS/DUMMYABFRL removal release (pr_ind_prs25062025_2); the Vedanta four-way demerger (pr_ind_prs23042026 and the 17/19/22 June 2026 exclusions); the reviewed DUMMYREL relationship (INDEX_PLACEHOLDER_FOR the pre-listing Jio entity, compared as s:JIOFIN, never merged with the instrument).
The adopted files in `docs/stage4/membership/` are UNCHANGED.

Conventions verified by tests: an interval end date is exclusive (the first day the stock is NOT a member); a handover is effective on the listing date but its announcement (known_at) is the date of the release that states it, never backdated.

## Agreement with the independent monthly checkpoints (revision 2 -> 3)

- N50_vs_monthly: 72/73 -> 73/73
- NEXT50_vs_monthly: 45/49 -> 49/49
- MID100_vs_monthly: 18/18 -> 18/18
- derived_N100_vs_monthly_N100: 18/18 -> 18/18
- derived_N100_vs_N50_plus_NEXT50_same_date: 45/49 -> 49/49
- derived_N200_vs_monthly_N200: 18/18 -> 18/18
- explicit_N100_sections_vs_monthly_N100: 18/18 -> 18/18
- explicit_N200_sections_vs_monthly_N200: 18/18 -> 18/18

Coverage by month: {'INCOMPLETE': 50, 'CLEAN': 23} -> {'INCOMPLETE': 54, 'CLEAN': 19} (months with a placeholder as a member are correctly INCOMPLETE)

## membership_events: 258 -> 282

- ADDED   `2025-04-07 | DUMMYSIEMS | ADD | pr_ind_prs02042025 | NEXT50/Nifty Next 50/p1`
- ADDED   `2025-05-22 | DUMMYABFRL | ADD | pr_ind_prs19052025 | MID100/Nifty Midcap 100/p1`
- ADDED   `2025-06-19 | DUMMYSIEMS | REMOVE | pr_ind_prs25062025_2 | NEXT50/placeholder replacement/p1`
- ADDED   `2025-06-19 | ENRIN | ADD | pr_ind_prs25062025_2 | NEXT50/placeholder replacement/p1`
- ADDED   `2025-06-23 | ABLBL | ADD | pr_ind_prs25062025_2 | MID100/placeholder replacement/p2`
- ADDED   `2025-06-23 | DUMMYABFRL | REMOVE | pr_ind_prs25062025_2 | MID100/placeholder replacement/p2`
- ADDED   `2025-06-27 | ABLBL | REMOVE | pr_ind_prs25062025_2 | MID100/Nifty Midcap 100/p2`
- ADDED   `2025-06-27 | ENRIN | REMOVE | pr_ind_prs25062025_2 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-04-30 | DUMMYVEDL1 | ADD | pr_ind_prs23042026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-04-30 | DUMMYVEDL2 | ADD | pr_ind_prs23042026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-04-30 | DUMMYVEDL3 | ADD | pr_ind_prs23042026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-04-30 | DUMMYVEDL4 | ADD | pr_ind_prs23042026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-06-15 | DUMMYVEDL1 | REMOVE | pr_ind_prs19062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | DUMMYVEDL2 | REMOVE | pr_ind_prs17062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | DUMMYVEDL3 | REMOVE | pr_ind_prs22062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | DUMMYVEDL4 | REMOVE | pr_ind_prs17062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | VAML | ADD | pr_ind_prs19062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | VEDPOWER | ADD | pr_ind_prs17062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | VISL | ADD | pr_ind_prs17062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-15 | VOGL | ADD | pr_ind_prs22062026 | NEXT50/placeholder replacement/p1`
- ADDED   `2026-06-19 | VEDPOWER | REMOVE | pr_ind_prs17062026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-06-19 | VISL | REMOVE | pr_ind_prs17062026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-06-23 | VAML | REMOVE | pr_ind_prs19062026 | NEXT50/Nifty Next 50/p1`
- ADDED   `2026-06-24 | VOGL | REMOVE | pr_ind_prs22062026 | NEXT50/Nifty Next 50/p1`

## membership_intervals: 329 -> 341

- ADDED   `i:2480 | VAML | 2480 | True | INSTRUMENT | 2026-06-15 | 2026-06-23 | EVENT`
- ADDED   `i:2492 | VEDPOWER | 2492 | True | INSTRUMENT | 2026-06-15 | 2026-06-19 | EVENT`
- ADDED   `i:2536 | VISL | 2536 | True | INSTRUMENT | 2026-06-15 | 2026-06-19 | EVENT`
- ADDED   `i:2550 | VOGL | 2550 | True | INSTRUMENT | 2026-06-15 | 2026-06-24 | EVENT`
- ADDED   `i:34 | ABLBL | 34 | True | INSTRUMENT | 2025-06-23 | 2025-06-27 | EVENT`
- ADDED   `i:707 | ENRIN | 707 | True | INSTRUMENT | 2025-06-19 | 2025-06-27 | EVENT`
- ADDED   `p:DUMMYABFRL | DUMMYABFRL |  | False | PLACEHOLDER | 2025-05-22 | 2025-06-23 | EVENT`
- ADDED   `p:DUMMYSIEMS | DUMMYSIEMS |  | False | PLACEHOLDER | 2025-04-07 | 2025-06-19 | EVENT`
- ADDED   `p:DUMMYVEDL1 | DUMMYVEDL1 |  | False | PLACEHOLDER | 2026-04-30 | 2026-06-15 | EVENT`
- ADDED   `p:DUMMYVEDL2 | DUMMYVEDL2 |  | False | PLACEHOLDER | 2026-04-30 | 2026-06-15 | EVENT`
- ADDED   `p:DUMMYVEDL3 | DUMMYVEDL3 |  | False | PLACEHOLDER | 2026-04-30 | 2026-06-15 | EVENT`
- ADDED   `p:DUMMYVEDL4 | DUMMYVEDL4 |  | False | PLACEHOLDER | 2026-04-30 | 2026-06-15 | EVENT`

## membership_exceptions: 12 -> 13

- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYABFRL | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYSIEMS | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYVEDL1 | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYVEDL2 | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYVEDL3 | N200`
- ADDED   `PLACEHOLDER_NOT_TRADABLE | p:DUMMYVEDL4 | N200`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | p:DUMMYABFRL | MID100`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | p:DUMMYABFRL | N200x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | p:DUMMYSIEMS | N100x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | p:DUMMYSIEMS | N200x`
- REMOVED `WALK_INCLUDED_BUT_NOT_MEMBER_AFTER | p:DUMMYSIEMS | NEXT50`

## membership_entity_equivalence: 1 -> 2

- ADDED   `p:DUMMYREL | s:JIOFIN`


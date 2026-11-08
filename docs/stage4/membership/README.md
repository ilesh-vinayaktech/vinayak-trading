# Nifty 200 membership, reconstructed backward 2020-10-01..2026-11-07 (PROVISIONAL, read-only)

Script: `scripts/reconstruct_nifty200_membership.py` (logic: `src/algo/data/membership_reconstruction.py`).
Nothing was written to the database; no coverage declared; no identity mapped; nothing person-verified.
Derived Nifty 200 = Nifty 50 + Next 50 + Midcap 100, walked back from the 2026-11-07 snapshots by undoing
every dated press-release transition. Counts are not forced to 200 (202 on 2020-10-01: two members
have no instrument, 200 tradable).

## Results
- Anchor check: derived union == explicit Nifty 200 snapshot today (200 = 200).
- Derived union vs the explicit-Nifty-200-sections walk: identical on all 21 change dates.
- 242 union events, 322 intervals. Undated or future-dated transitions applied: none (0 unplaced).
- Walk inconsistencies kept as exceptions: 5 (derived), 6 (explicit N200), 2 (explicit N100), e.g. CENTRALBK/IDEA/IREDA
  Midcap 100 2024, and the two DUMMY placeholders.
- Monthly PDF checkpoints exist only to 2022-03-31 (Midcap 100, N100, N200: 18 dates) and cover all five
  months-end for N50/Next 50. Exact agreement is low: N50 35/73, Next 50 45/49, Midcap 100 0/18, N200 0/18.
  Every disagreement traces to a few entities (below), not to scattered noise.

## What cannot be established (blocked per entity, never the whole universe)
| Entity | Blocked span | Evidence |
|---|---|---|
| NESTLEIND (unmapped symbol; instrument has the new ISIN) | whole window | ISIN identities kept separate per owner decision |
| JIOFIN, NESTLEIND instrument | ~2023-08..2024-04 | reconstruction has them in the union, the snapshot does not; lead: unparsed release pr_ind_prs17072023 (a person must read it) |
| BSE (i:417) | 2020-10-01..2026-09-30 | Midcap 100 mismatch in all 18 snapshots; the parsed 2026-08-10 release also lists BSE under Nifty 50, which needs manual reading before anything depends on it |
| ITCHOTELS | 2025-01-29..anchor | demerger/placeholder releases unparsed (pr_ind_prs06022025_1) |
| GSPL, PEL | member without instrument | stay unmapped per owner decision |
| DUMMY* placeholders | not tradable | reported, not blocked |

Every date is therefore INCOMPLETE in `membership_coverage.json` (73/73): either an unmapped member or a
blocked entity is present. That is the honest answer today; it is not wrong data.

## Next
1. A person reads: pr_ind_prs17072023 (JIOFIN/NESTLE), the 2026-08-10 release (BSE), pr_ind_prs06022025_1 (ITCHOTELS).
2. DHANI/MINDTREE/PEL/GSPL dates from the source documents.
3. Then declare coverage only for spans a person verified. Do not register until readiness passes.

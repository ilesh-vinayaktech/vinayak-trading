# Nifty 200 membership, reconstructed backward 2020-10-01..2026-11-07 (PROVISIONAL, read-only)

Script: `scripts/reconstruct_nifty200_membership.py` (logic: `src/algo/data/membership_reconstruction.py`).
Nothing was written to the database; no coverage declared; no identity mapped; nothing person-verified.
Derived Nifty 200 = Nifty 50 + Next 50 + Midcap 100, walked back from the 2026-11-07 snapshots by undoing
every dated press-release transition. Counts are not forced to 200 (202 on 2020-10-01: two members
have no instrument, 200 tradable).

## Results (revision 2, 2026-11-09; revision 1 is in git history, the change list is DIFF_v1_to_v2.md)
- Anchor check: derived union == explicit Nifty 200 snapshot today (200 = 200).
- 258 union events, 329 intervals. Undated or future-dated transitions applied: none (0 unplaced).
- Agreement with the monthly PDF checkpoints: Nifty 50 72/73, Next 50 45/49, Midcap 100 18/18, derived and explicit N100 18/18, derived and explicit N200 18/18 (revision 1: 35, 45, 0, 0, 0).
- Coverage by month (all still PROVISIONAL, nothing declared in the database): 23 CLEAN, 50 INCOMPLETE.
- What changed it: parser v7 (page-continued and "excluded from the following indices" releases), six reviewed
  revocations (`membership_cancellations.csv`), four reviewed placeholder replacements (ITCHOTELS, TMCV, KWIL, JIOFIN),
  one reviewed entity equivalence (`membership_entity_equivalence.csv`), BSE's 2024-03-28 inclusion. Every one is a
  config file with its source hash and the review decision it rests on; no identity or alias table was changed.

## What remains (exceptions: 12)
| Kind | Entities | Why it is left |
|---|---|---|
| WALK_INCLUDED_BUT_NOT_MEMBER_AFTER (5) | DUMMYABFRL, DUMMYSIEMS placeholders | the release that removes each placeholder was not read; decisions recorded as RECONSTRUCTION_CORRECT |
| MEMBER_WITHOUT_INSTRUMENT (4) | GSPL, PEL, JIOFIN (pre-listing span) | no instrument in the master / pre-listing; the apply step must create them from the reviewed decisions |
| PLACEHOLDER_NOT_TRADABLE (3) | DUMMYITC, DUMMYTATAM, DUMMYHDLVR | non-tradable by design; replaced by the listing on its listing date |

## Known limits
- The older universe pipeline (universe_build) does not see revocations or replacements; only this reconstruction does.
- Next 50 still disagrees with 4 monthly snapshots (10 entity differences): not yet investigated.
- Nothing here is person-verified coverage; do not register the strategy until readiness passes.

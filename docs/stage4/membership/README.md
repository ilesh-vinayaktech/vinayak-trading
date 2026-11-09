# Nifty 200 membership, reconstructed backward 2020-10-01..2026-11-07 (PROVISIONAL, read-only)

Script: `scripts/reconstruct_nifty200_membership.py` (logic: `src/algo/data/membership_reconstruction.py`).
Nothing was written to the database; no coverage declared; no identity mapped; nothing person-verified.
Derived Nifty 200 = Nifty 50 + Next 50 + Midcap 100, walked back from the 2026-11-07 snapshots by undoing
every dated press-release transition. Counts are not forced to 200 (202 on 2020-10-01: two members
have no instrument, 200 tradable).

## Results (revision 3, 2026-11-09; revision 2 is commit 590466f, changes in DIFF_v2_to_v3.md and DIFF_v1_to_v2.md)
- Anchor check: derived union == explicit Nifty 200 snapshot today (200 = 200).
- 282 union events, 341 intervals. Undated or future-dated transitions applied: none (0 unplaced).
- Agreement with every independent monthly checkpoint: Nifty 50 73/73, Next 50 49/49, Midcap 100 18/18, derived and explicit N100 18/18, derived and explicit N200 18/18 (revision 1: 35, 45, 0, 0, 0).
- Coverage by month (all PROVISIONAL, nothing declared in the database): 19 CLEAN, 54 INCOMPLETE. A month with a placeholder as a member is INCOMPLETE by design; the CLEAN count was not optimised.
- Built from: parser v7; six reviewed revocations (`membership_cancellations.csv`); reviewed placeholder replacements
  (ITCHOTELS, TMCV, KWIL, JIOFIN, ENRIN, ABLBL, VAML, VEDPOWER, VOGL, VISL); two reviewed entity equivalences
  (`membership_entity_equivalence.csv`: NESTLEIND keys, DUMMYREL as the index placeholder for the pre-listing Jio entity);
  hand transcriptions of notices the parser refuses. Each is a config file with its source hash and the review decision it
  rests on. No identity or alias table was changed.
- NESTLEIND handover (2026-11-09): intervals of an ISIN-changed issuer are cut at the VERIFIED conversion date (HANDOVER_REVIEW.md); only membership_intervals.csv changed.
- Conventions (tested): an interval end date is exclusive; a handover is effective on the listing date but its
  announcement date (`known_at`) is the date of the release that states it, never backdated.

## What remains (exceptions: 13) - NOT resolved by adopting this revision
| Kind | Entities | What is needed |
|---|---|---|
| MEMBER_WITHOUT_INSTRUMENT (4) | GSPL; JIOFIN pre-listing span; PEL (2 spans) | identity/application work: create or map instruments from the reviewed decisions (the apply step, not built) |
| PLACEHOLDER_NOT_TRADABLE (9) | DUMMYITC, DUMMYTATAM, DUMMYHDLVR, DUMMYSIEMS, DUMMYABFRL, DUMMYVEDL1-4 | non-tradable by design; replaced by the listing on its listing date |

## Known limits
- Point-in-time: for ENRIN, ABLBL, the Vedanta securities and the other replacements, the later exclusion release is the
  only evidence stored for the listing-date handover. It is retrospective, not proof the handover was publicly knowable on the
  listing date. Keep `effective_before_announcement = True` and use the announcement date as `known_at`. The contemporaneous
  NSE listing notices are not stored; fetch them before relying on listing-date knowledge.
- The older universe pipeline (universe_build) does not see revocations or replacements; only this reconstruction does.
- Nothing here is person-verified coverage; do not register the strategy until readiness passes.

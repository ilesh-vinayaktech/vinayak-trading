# Nifty 200 membership, reconstructed backward 2018-04-02..2026-11-07 (revision 4 candidate, PROVISIONAL, read-only)

Same method and script as revision 3 (`docs/stage4/membership/`, which is unchanged): `scripts/reconstruct_nifty200_membership.py --start 2018-04-02 --anchor-date 2026-11-07 --out docs/stage4/membership-2018`.
Nothing was written to the database, no coverage declared, no identity mapped, nothing person-verified. 2018-04-02 is when the current Nifty 200
definition (Nifty 50 + Next 50 + Midcap 100) began; before it the index was built differently and needs its own derivation (not done).

## What changed from revision 3
1. **The window starts at 2018-04-02** instead of 2020-10-01 (the old start was only a default argument, not a data limit).
2. **Null-and-void releases are honoured.** The 2020-05-13 release states that the replacements announced on 18 February, 12 March and 19 March 2020 for
   27 March 2020 "shall stand null and void" (the review was redone on 10 June and took effect 26 June). The project already held these as three VOID rows in
   `index_release_override`; the reconstruction did not read them because its old window began after March 2020. `apply_voids` now drops exactly those
   transitions (same release, same effective date): 56 transitions (54 from 18 Feb, 2 from 19 Mar). A void that matches nothing is reported, not ignored (the 12 March
   release had no Nifty-component change for 27 March). Listed in `membership_voids.csv`. The 19 March Nifty 50 change that took effect on 19 March stands.
   Rerunning the 2020-10-01 window with this code gives byte-identical revision 3 files.

## Agreement with the independent monthly constituent snapshots (2018-04 onward)
| Check | Result |
|---|---|
| Nifty 50 | 103 of 103 |
| Nifty Next 50 | 79 of 79 |
| Nifty Midcap 100 | 48 of 48 (before the void fix: 25 of 48, all the Yes Bank March 2020 episode) |
| Explicit Nifty 100 and Nifty 200 sections of the releases | 48 of 48 each |
| Derived Nifty 200 / Nifty 100 | 22 of 48: every one of the 26 differing months (2018-04-30 to 2020-05-29) differs by ONE stock, TATAMTRDVR |
| Walk consistency (a transition undone from a state that contradicts it) | 0 (was 56) |

## Exceptions (16)
| Kind | Entities | Needs |
|---|---|---|
| SNAPSHOT_MISMATCH_BLOCK (1) | TATAMTRDVR (Tata Motors DVR), blocked 2018-04-02..2020-06-30 | evidence for its exit: it is in the monthly Nifty 100 and Nifty 200 snapshots through 2020-05-29 and gone by 2020-06-30, but no captured release names it (the 10 June 2020 review and the 13 May release do not), and the monthly Next 50 lists do not show it although Nifty 100 does. Strict mode blocks the stock for that span; nothing is guessed |
| MEMBER_WITHOUT_INSTRUMENT (6) | BHARATFIN (to 2018-12-28), HEXAWARE (to 2020-09-25), GSPL (to 2023-03-31), JIOFIN pre-listing, PEL twice | instrument identity (delisted names with no instrument; the apply step is not built). BHARATFIN and HEXAWARE are new in this window |
| PLACEHOLDER_NOT_TRADABLE (9) | the DUMMY* demerger placeholders (2025-2026) | non-tradable by design, as in revision 3 |

## Limits
- Not done: before 2018-04-02; prices for members that delisted before the NSE bars begin (2019-10) are not loaded, so those sessions stay incomplete until the older bhavcopy is.
- Point-in-time limits of revision 3 still apply (listing-date handovers of ENRIN, ABLBL and the Vedanta securities rest on later releases).
- `index_membership_event` and `index_membership_coverage` are still empty in the database: this is the evidence to verify and then load.

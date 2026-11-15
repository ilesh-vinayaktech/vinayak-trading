# Review pack: Nifty 200 membership 2018-04-02 to 2026-11-07 (revision 4 candidate)

For the owner, to sign off. About 15 minutes: four decisions and six spot checks. UPDATE 2026-11-15: the identities of D2/D3 are applied to the dev DB and the reconstruction is loaded as PROVISIONAL (566 events, one coverage). Your sign-off is
what lets me mark it VERIFIED; until then no strict-mode (point-in-time) Nifty 200 experiment can be registered. 

**Owner sign-off received 2026-11-15:** D1 approve; D2 approve; D3 approve identity and re-mapping, bars held; D4 accept placeholders but they must stay in membership; D5 accept the knowledge-date limit but keep the real effective dates. Both blockers are built (migration 072): every event stores `effective_from` (when it really applied), `announcement_date` (when it could have been known) and `ingested_at` (when recorded); strict point-in-time queries use the announcement date, `historical=True` the effective date; placeholders and unmapped symbols are stored as members by `constituent_key` (`constituents_on`), separate from tradable instruments (`members_on`). Reloaded: 586 PROVISIONAL events (20 with effective before announcement, 20 without an instrument).

## What you are signing
That the reconstructed membership (`membership_intervals.csv`, 391 intervals) is an accurate record of who was in the Nifty 200 on each day, except where
this pack says a stock has no instrument. The evidence for it is that it matches every independent source we hold:

| Independent source | Agreement |
|---|---|
| Month-end constituent lists, Nifty 50 | 103 of 103 months |
| Month-end constituent lists, Nifty Next 50 | 79 of 79 |
| Month-end constituent lists, Nifty Midcap 100 | 48 of 48 |
| The releases' own explicit Nifty 100 and Nifty 200 tables | 48 of 48 each |
| Derived Nifty 200 against the month-end Nifty 200 lists | **48 of 48** |

Member counts: 200 on every month-end checked; by session the count is 201 until 2020-06-25 (Tata Motors DVR is the 101st Nifty 100 member, D1) and otherwise 200, except 1,007 sessions in total at 201 to 204 (the DVR, and spun-off entities that NSE adds on top of the parent until it excludes them, not placeholder/listing duplicates). Every session above 200 is explained, with NSE release evidence, in `membership_counts.md` (checked by `scripts/check_membership_counts.py`): Tata Motors DVR as a 101st member, and demerged entities added on top of their parent until NSE excludes them; no placeholder ever overlaps its real listing. Before D2/D3 were applied 196 were tradable instruments on 2018-04-02; the rest were the stocks in D2 and D3.

## Decisions

**D1. TATAMTRDVR (Tata Motors DVR): resolved, no decision needed.** It was blocked for 26 months because the derived list followed only the Nifty 50, Next 50 and Midcap 100 sections. NSE lists
this stock as a 101st member of the Nifty 100 outside those, and its whole history is in NSE's own releases already in our lake: member to 2020-06-25 (10 June 2020 release), out until
2023-09-28, member again from 2023-09-29 (17 Aug 2023 release), excluded from 2024-08-30 (23 Aug 2024 release, capital reduction cancelling the DVR shares). It is now two ordinary intervals,
and the derived Nifty 200 matches all 48 month-end lists. **Side effect to know about:** revision 3 was missing this stock for 2023-09-29 to 2024-08-29 (11 months); this revision fixes it.
- Just confirm it in the spot check below.

**D2. BHARATFIN and HEXAWARE have no instrument** (both new in this window). Stored proposals (`docs/stage4/apply_proposals/proposals.md`): each becomes
its own historical instrument, with its merger as a dated relationship, not an alias. BHARATFIN: member 2018-04-02 to 2018-12-28 (184 sessions), merged into IndusInd Bank on
2019-07-04, last traded 2019-07-02, so **we have no prices for it** (before 2019-10). HEXAWARE: member to 2020-09-25 (616 sessions), delisted 2020-11-09, its prices from 2019-10 are in the stored raw files.
- **Dry run done 2026-11-15** (`docs/stage4/identity/2026-11-15_bharatfin_hexaware_dry_run.md`, config `config/identity_applications/bharatfin_hexaware.json`, rolled back, nothing persisted): +2 instruments, +2 aliases, +1 relationship (BHARATFIN into IndusInd Bank, 639:1000 effective 2019-07-04, now also confirmed by IndusInd's own FAQ, still PROVISIONAL; HEXAWARE has none, per your decision 13: the 2025 HEXT relisting is deliberately not linked), 218 release rows and 202 monthly rows re-mapped (exactly the unmapped counts), every unrelated record set byte-identical.
- **Owner: approved; applied to the dev DB 2026-11-15** (`docs/stage4/identity/applied_bharatfin_hexaware/`). BHARATFIN's sessions stay incomplete until older prices are loaded.

**D3. GSPL and PEL have no instrument; a full review package already exists: `docs/stage4/identity/GSPL_PEL_REVIEW.md`** (built and tested; applied 2026-11-15, identity and re-map only, bars held). GSPL is a member
2018-04-02 to 2023-03-31 (1,240 sessions); PEL 2018-04-02 to 2022-08-08 and 2023-03-31 to 2024-09-30 (1,451 sessions). Both traded throughout: a naming gap, not a missing company. That
package makes each its own historical instrument (GSPL, INE246F01010, merged into GUJENERGY on 2026-05-01; PEL, INE140A01024, merged into PIRAMALFIN on 2025-09-16), re-maps their
unmapped release and snapshot rows, and moves no membership to the successors. Its own recommendation, which I share: **apply the identity and re-map now, hold the price bars** until their corporate
actions are loaded (PEL closes fall by 45% on 2022-08-30, the Piramal Pharma demerger, with no action recorded). The GSPL merger ratio (10:13) is from search results only, so that relationship is PROVISIONAL.
About 370 sessions of each fall before our NSE prices begin.
- **Dry run re-done 2026-11-15** (`docs/stage4/identity/2026-11-15_gspl_pel_dry_run.md`, rolled back): +2 instruments, +2 aliases, +2 relationships, 566 release rows and 417 monthly rows re-mapped, every unrelated record set (including GNRL, GUJENERGY, PIRAMALFIN) byte-identical.
- **Owner: approved identity and re-map, bars held; applied to the dev DB 2026-11-15** (`docs/stage4/identity/applied_gspl_pel/`).

**D4. Nine placeholders** (DUMMYITC, DUMMYTATAM, DUMMYHDLVR, DUMMYSIEMS, DUMMYABFRL, DUMMYVEDL1 to 4; 2025 and 2026). They are not tradable by design and are replaced by the real
listing on its listing date. Same as revision 3.
- **Owner: accepted, with the condition that placeholders stay members** (`constituent_key`, done).

**D5. Retrospective listing handovers.** For ENRIN, ABLBL and the Vedanta securities, the only evidence of the listing-date handover is a later release, so it is
not proof the handover was publicly known on that day. We keep the announcement date as the date the platform "knew" it.
- **Owner: accepted; real effective dates kept apart from announcement dates (done).**

## Spot checks (10 minutes)
Open `membership_intervals.csv` and filter on the symbol; compare with the NSE index factsheet or press release you trust. `end_exclusive` is the first day the stock is no longer a member.

| Symbol | The file says | What to check |
|---|---|---|
| YESBANK | member 2018-04-02 to 2020-03-19 (exclusive), member again from 2020-09-25 | removed from the index on 2020-03-19 after the Yes Bank reconstruction scheme |
| IRCTC | member from 2020-06-26 | added in the June 2020 review |
| ASHOKLEY | member the whole window | stays in through the 2020 review (it moved between Next 50 and Midcap 100) |
| IDEA | member the whole window | |
| HEXAWARE | member to 2020-09-25, no instrument | gone from the index in the September 2020 review |
| TATAMTRDVR | member 2018-04-02 to 2020-06-26 (exclusive) and 2023-09-29 to 2024-08-30 (exclusive) | out in June 2020, back in the September 2023 review, out when the DVR shares were cancelled |

## What this does not cover
Anything before 2018-04-02 (the index was built differently and needs its own derivation). Prices for members that delisted before 2019-10 (older NSE price files are not loaded).
Person verification itself: until you sign, everything is PROVISIONAL.

## Status after owner sign-off (2026-11-15)
D1 to D5 are signed with the conditions above. Done: both identity applications, the loader (586 PROVISIONAL events, one coverage), the two-date and constituent-key model (migration 072), and the session-count explanation. The last open point, the 201 to 204 session counts, is explained in `membership_counts.md`. **The owner approved VERIFIED on 2026-11-15**; the 586 events and the coverage were marked VERIFIED in the dev DB (`VERIFICATION.md`). Membership only: prices, corporate actions and instrument identity are still separate gates.

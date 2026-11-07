# Nifty 200 history: evidence review (2026-11-07)

Status: **nothing is stored as membership and no coverage is declared.** The derivation
(`scripts/derive_universe.py`) reports; it does not force 200 members.

## What the evidence now says

* Corpus: 204 NSE Indices press releases from 2017 on, all classified:
  160 PARSED, 20 NOT_RELEVANT, 21 MANUAL_REVIEW_REQUIRED, 3 UNSUPPORTED_FORMAT (scanned images).
* **March 2020 is resolved by a documented supersession.** The 27 Mar 2020 rebalancing was deferred
  (23 and 25 Mar 2020); the 13 May 2020 release states the 27 Mar replacements "shall stand null and
  void" except Nifty 50 / Nifty Bank, which had been rebalanced on 19 Mar (the 16 Mar release). This is
  recorded in `index_release_override` with the literal quote (`scripts/record_overrides.py`), the 56
  voided rows stay visible in the report.
* **2018-04-02 is a definition change**, not an ordinary review: Nifty 200's midcap component changes
  from Full to Free-float Midcap 100. Events on that date are not emitted as membership changes; the
  `NIFTY200` series begins with the state after it (`NIFTY200_M1` covers the earlier definition).
  A parser bug (sub-headed sections) had hidden 101 Midcap 100 rows from the 2018-02-21 release.
* A parser bug (dates wrapped across lines) had left 1,363 rows undated; fixed (parser v2). Parser v4
  classifies every document explicitly.

## Archive search (2026-11-07)

niftyindices.com publishes only CURRENT constituent lists and factsheets; no historical constituent
archive is linked (history is sold via the NSE index data subscription). Captured instead, untouched in
the lake: today's Nifty 50 / Next 50 / Midcap 100 / Nifty 200 lists (with ISINs) and the equity-index
methodology PDF. Independent check: the three component lists are disjoint and their union is exactly the
Nifty 200 list (50 + 50 + 100 = 200, no differences). They are loaded as dated snapshots and used for a
**component-level** check (each component's last event vs its own current list, before the union).

## Monthly constituent archive (2026-11-07)

118 monthly archives (Jan 2017 - Oct 2026, 321 MB) are stored untouched with checksums
(`scripts/capture_monthly_archive.py`: sequential, 7 s delay, stops on refusal; the log records 3 x HTTP 504
and a clean resume). They are parsed (`scripts/parse_monthly_snapshots.py`, 0 parser problems) into 410
month-end snapshots. **Snapshots are month-end evidence, not events**: they are kept apart from the
press-release events and no effective date is derived from them.

**Coverage limit:** the archive is comprehensive (32-43 index PDFs a month) only through March 2022. After
that NSE publishes only Nifty 50, Bank, Financial Services, Midcap Select, IT (and Next 50 from April 2024).
So official month-end evidence for **Nifty 200 and Midcap 100 exists only for 2017-01 .. 2022-03**.

**Month-to-month reconciliation** (`scripts/reconcile_monthly.py`; snapshot k + press-release events between
the two report dates vs snapshot k+1; every finding with nearby events is in
`data/reports/monthly_reconciliation.csv`):

| Index | Snapshots | Transitions | Reconcile exactly |
|---|---:|---:|---:|
| Nifty 50 (2017-01 .. 2026-10) | 118 | 117 | 107 |
| Nifty Next 50 | 94 | 93 | 90 |
| Nifty 100 | 63 | 62 | 60 |
| Nifty Midcap 100 | 63 | 62 | 58 |
| Full Midcap 100 (pre-2018 only) | 9 | 8 | 7 |
| Nifty 200 | 63 | 62 | 58 |

Clusters found and resolved by reading the evidence (not by tuning):
* **Sep 2020 (58)**: parser did not accept LETTERED section headings (`a) NIFTY 50`).
* **Feb 2018 (18), Jun 2018 (8), most of Sep 2017**: headings of the form "NIFTY 50 Index" were not mapped
  to a component (parser v6).
* **Sep 2021 (52)**: the review is in `pr_ind_prs23082021`, a SCANNED image. Re-fetched (identical bytes), the
  effective date is stated on page 1 ("effective from September 30, 2021 (close of September 29, 2021)") and in
  `pr_ind_prs15092021`; a local OCR transcription (`config/transcriptions/`, loaded by
  `scripts/apply_transcriptions.py`) matches the official month-end snapshots EXACTLY for Nifty 50, Next 50,
  Nifty 100, Midcap 100 and Nifty 200 (5/5, 10/10, 6/6 changes) and a visual check of page 10. Provisional;
  no date was invented. The REIT/InvIT revocation in the 15 Sep release does not touch these indices.

Still open: **2018-04 (101)** = the Midcap 100 definition change (expected, modelled as a boundary);
2017-09 (8), 2017-12 (6), 2017-05 (4), 2023-08, 2026-04, 2026-06 (4 each).

Also found: counts of 51 / 101 / 201 are real - the Tata Motors DVR (`TATAMTRDVR`) is a second share class of
one company inside Nifty 50, Nifty 100 and Nifty 200 in some periods, so "50 / 100 / 200" counts SYMBOLS only
approximately. The Nifty 200 PDF also lists a member that none of Nifty 50 / Next 50 / Midcap 100 lists on
the same date (33 union mismatches), so "Nifty 200 = union of the three" is not exact historically. Treat
that relationship as a CURRENT composition fact only; the directly published Nifty 200 snapshots (2017-01 ..
2022-03) are kept as an independent series, and later periods are reconstructed with explicit coverage.

## Still unresolved

| Kind | Count | Meaning |
|---|---:|---|
| NON_ALTERNATING | 15 | a component event repeats (an event between is missing) |
| SNAPSHOT_MISMATCH | 22 | last derived state disagrees with the current official list |
| CHECKPOINT_MISSING / EXTRA | 15 / 12 | explicit "NIFTY 200" rows not reproduced / derived changes not listed |
| UNMAPPED_EVENT / PLACEHOLDER_EVENT | 19 / 5 | symbols with no instrument (PEL, DALMIABHA, ABIRLANUVO, BHARATFIN, NESTLEIND, GSPL) / dummy symbols (DUMMYSIEMS, DUMMYABFRL) |
| COMPONENT_SNAPSHOT_MISMATCH | 57 | a component's last event disagrees with its own current list: Midcap 100 35, Next 50 19, Nifty 50 3; clustered at 2022-09-30 (13), 2020-06-26 (5), 2023-03-31, 2019-09-27, 2021-03-31, 2022-03-31 |
| MANUAL_DOCUMENT | 24 | releases a person must read (below) |

Backward member counts differ from 200 at all 22 change dates (198..214); they are reported as is.
HUDCO: excluded 2021-03-31 and 2026-09-30 with no inclusion between; no captured release contains one.
Problems cluster at 2017-09-29, 2026-03-30, 2024-03-28, 2022-09-30, 2020-06-26, 2023-03-31.

Some semi-annual dates (Sep 2021, Sep 2023, Sep 2024, Mar 2025) have no Nifty 50 / Next 50 /
Midcap 100 section in the captured releases. That may mean "no change in those indices" or "published
elsewhere"; it is not assumed either way.

## Documents a person must read

| Announced | Document | Classification |
|---|---|---|
| 2017-03-06 | pr_ind_prs06032017_1 | MANUAL_REVIEW_REQUIRED |
| 2017-08-22 | pr_ind_prs22082017 | MANUAL_REVIEW_REQUIRED |
| 2018-01-05 | pr_ind_prs05012018 | MANUAL_REVIEW_REQUIRED |
| 2018-06-15 | pr_ind_prs15062018_1 | MANUAL_REVIEW_REQUIRED |
| 2018-09-24 | pr_ind_prs24092018 | UNSUPPORTED_FORMAT |
| 2020-05-13 | pr_ind_prs13052020 | MANUAL_REVIEW_REQUIRED |
| 2020-08-20 | pr_ind_prs20082020 | MANUAL_REVIEW_REQUIRED |
| 2021-02-23 | pr_ind_prs23022021_1 | MANUAL_REVIEW_REQUIRED |
| 2021-08-23 | pr_ind_prs23082021 | UNSUPPORTED_FORMAT |
| 2023-03-22 | pr_ind_prs22032023 | MANUAL_REVIEW_REQUIRED |
| 2023-06-19 | pr_ind_prs19062023 | UNSUPPORTED_FORMAT |
| 2023-07-17 | pr_ind_prs17072023 | MANUAL_REVIEW_REQUIRED |
| 2024-01-19 | pr_ind_prs19012024 | MANUAL_REVIEW_REQUIRED |
| 2024-09-25 | pr_ind_prs25092024 | MANUAL_REVIEW_REQUIRED |
| 2024-12-30 | pr_ind_prs30122024 | MANUAL_REVIEW_REQUIRED |
| 2025-02-06 | pr_ind_prs06022025_1 | MANUAL_REVIEW_REQUIRED |
| 2025-06-25 | pr_ind_prs25062025_2 | MANUAL_REVIEW_REQUIRED |
| 2025-10-07 | pr_ind_prs07102025 | MANUAL_REVIEW_REQUIRED |
| 2025-11-13 | pr_ind_prs13112025 | MANUAL_REVIEW_REQUIRED |
| 2025-11-28 | pr_ind_prs28112025 | MANUAL_REVIEW_REQUIRED |
| 2026-02-20 | pr_ind_prs20022026_1 | MANUAL_REVIEW_REQUIRED |
| 2026-06-17 | pr_ind_prs17062026 | MANUAL_REVIEW_REQUIRED |
| 2026-06-19 | pr_ind_prs19062026 | MANUAL_REVIEW_REQUIRED |
| 2026-06-22 | pr_ind_prs22062026 | MANUAL_REVIEW_REQUIRED |

(The reason and the extracted text for each are in `index_release_document.classification_reason` /
`extracted_text`.) Several are corporate-action notices naming several companies or several dummy
symbols (Tata Motors/TMCV, ITC Hotels, Siemens Energy, Vedanta x4, Kwality Wall's): parsed only when
unambiguous, never guessed.

## Identity records that are assertions, not verified evidence

* IBVENTURES -> DHANI (same company, symbol change effective 2020-10-28): recorded as
  `asserted_pending_isin_check`. The company intimation (2020-10-06) and NSE circular NSE/CML/46118
  (2020-10-22) are not yet in the lake; ISIN continuity is unchecked.
* The 18 delisted instruments are inferred from bhavcopy disappearance (`meta.verified=false`).

## Not done yet

Component-level reconstruction before the union; reading the 24 documents; finding releases published
outside the press-release index (the Midcap 100 / Nifty 200 constituent files and factsheet archive);
benchmark TRI history; verified cost schedules; confirmed validation thresholds.

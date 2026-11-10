# GSPL and PEL identity application: review package (NOT APPLIED; nothing in production changed)

Config: `config/identity_applications/gspl_pel.json` (built from the recorded proposals, review decisions 12 and 16, KEEP_SEPARATE). Code: `src/algo/data/identity_application.py`
(100% line/branch), `scripts/apply_identity_application.py` (dry run by default). Dry-run diffs on production (rolled back): `gspl_pel_dry_run_identity_only.md/.json`,
`gspl_pel_dry_run_with_bars.md/.json`. Recomputed membership metrics come from a real apply on disposable restores of production (production untouched).

## 1. The mappings (each is a distinct security, never an alias onto the successor)
| | GSPL | PEL |
|---|---|---|
| New historical instrument | Gujarat State Petronet Limited, **INE246F01010**, delisted, listed_on NULL, first observed 2006-02-16, last traded 2026-05-11 | Piramal Enterprises Limited, **INE140A01024**, delisted, listed_on NULL, first observed 2012-09-21, last traded 2025-09-22 |
| Alias (nse) | GSPL 2006-02-16 (FIRST_OBSERVED) .. 2026-05-12 (LAST_OBSERVED), no overlap | PEL 2012-09-21 (FIRST_OBSERVED) .. 2025-09-23 (LAST_OBSERVED) |
| Relationship asserted | **AMALGAMATED_INTO** instrument 907 GUJENERGY (**INE844O01030**), effective 2026-05-01, last source session 2026-05-11, ratio 10:13 | **MERGED_INTO** instrument 1761 PIRAMALFIN (**INE202B01038**), effective 2025-09-16, last source session 2025-09-22, **no ratio stored** |
| Evidence | NSE Indices release 2026-05-04 (read); company filings (read): amalgamation of GSPC, GSPL and GEL into Gujarat Gas, appointed date 2024-04-01, effective 2026-05-01; ratio 10:13 from search results only | PEL filing 2025-09-16 (read): scheme effective 2025-09-16; record date 2025-09-23; PFL letter 2025-11-04: shares trade from 2025-11-07; 1:1 not verified so not stored |
| Status | PROVISIONAL (ratio not from a primary filing) | PROVISIONAL |
| Guards | never GNRL (849, INE207H01026, a different company, untouched); successor is GUJENERGY | old PEL stays a separate security from Piramal Finance; MERGED_INTO, not a same-issuer alias; no membership transfer |
`last_source_session` is derived from the instrument's last traded day (not in the original proposal). Instrument ids are assigned at apply time (dry run 2656/2657; sandboxes 2660/2661).

## 2. Exactly which persisted records change (identity stage; production dry run, rolled back)
instrument +2, instrument_alias +2, corporate_action_relationship +2, press-release rows re-mapped **566** (GSPL 210 and PEL 379 were unmapped; leftovers: GSPL 2 undated rows,
PEL 21 exclusions dated 2025-09-30, after its last session: correctly NOT mapped), monthly constituents re-mapped **417**. The re-map is limited to these two symbols (the
unrestricted existing `remap()` would also have re-mapped the 27 stale NESTLEIND release rows and 114 monthly rows, a separate effect). All 12 fingerprints outside the
intended set are identical before and after, including GNRL, GUJENERGY and PIRAMALFIN (instrument + alias + bars) and every other instrument's bars.
Neither relationship type is read by the engine, reader or ledger (only SAME_ISSUER_ISIN_CHANGE is), so no implicit conversion or issuer splice can result.

## 3. Membership: unchanged by the identity application
Reconstruction on the sandbox: events (282) and intervals (342) equal the committed files once `s:GSPL` and `s:PEL` are relabelled to their new instrument ids: no event added, removed
or re-dated, **no membership transferred to GUJENERGY or PIRAMALFIN**. Every independent-checkpoint comparison is identical to the committed one (Nifty 50 73/73, Next 50 49/49,
Midcap 100 18/18, derived and explicit N100 and N200 18/18). Exceptions: MEMBER_WITHOUT_INSTRUMENT 4 -> 1 (JIOFIN pre-listing remains); months classed CLEAN 19 -> 65.

## 4. Before / after (sessions 2020-10-01..2026-11-06, 1,513 sessions; strict-eligible is 0 in every row: nothing is person-verified)
| scenario | member sessions COMPLETE | eligible once verified | notes |
|---|---|---|---|
| today | 356 | 337 | PEL and GSPL members have no instrument |
| identity + re-map only | 356 | 337 | tradable members now, but no bars: reported as "member without a bar", not hidden |
| identity + re-map + bars | 1,325 | 1,295 | bars: GSPL 1,639 (2019-10-01..2026-05-11), PEL 1,485 (..2025-09-22); 3,124 rows, 152 holiday/unloaded files skipped |
The 32 retrospective sessions stay ineligible in every scenario. 1,295 is a potential count after verification, not today's strict count.

## 5. DEPENDENCY THAT BLOCKS THE BAR STAGE: corporate actions
The lake holds corporate-action files for exactly 200 symbols; none for GSPL or PEL, so `corporate_action` has 0 rows for either. The existing action reparse also skips any instrument whose alias has an
end date. Loading the bars first would give these two names a clean strict-mode record while their prices are unadjusted. The new bars already show it: PEL closes 1,926.50 -> 1,063.55
on **2022-08-30** (x0.5521, the Piramal Pharma demerger ex-date) with no action recorded, and there are 11 other moves over 10% (mostly March 2020 market-wide); GSPL has 3 (largest x0.80, 2024-04-22).
**Recommendation: apply identity + re-map first (safe, reversible, no bars). Hold the bar stage until their corporate actions are loaded and the PEL demerger is resolved (an exchange base
price exists for 2022 only if NSE ran a special session; otherwise it is a pre-2023 case like the four held demergers).** Until then the new instruments stay "member without a bar" and strict mode
cannot use them.

## 6. Other dependents checked
Conversions: none involved (no SAME_ISSUER_ISIN_CHANGE). Blocked spans: none recorded for these entities. Held positions: the momentum strategy does not hold names after they leave the index
(PEL left 2024-09-30, GSPL 2023-03-31, long before their last trading days), so no stranded position arises; an engine rule for a position held at a merger is a separate open item.
Production procedure when approved: backup + restore test, final dry run with a preserved manifest, no writers, `apply_identity_application.py --apply`, then the fingerprint comparison above.

# Apply proposals (PROPOSAL ONLY, nothing applied)

28 recorded review decisions -> proposals. No write was made to the instrument master, aliases, membership or coverage tables.

| item | decision | kind | writes |
|---|---|---|---|
| symbol:ABIRLANUVO | KEEP_SEPARATE (#1) | HISTORICAL_INSTRUMENT | 3 |
| symbol:BHARATFIN | KEEP_SEPARATE (#2) | HISTORICAL_INSTRUMENT | 3 |
| symbol:DALMIABHA | KEEP_SEPARATE (#3) | HISTORICAL_INSTRUMENT | 3 |
| symbol:DHANI | CONFIRM_MAPPING (#4) | ALIAS_ALREADY_PRESENT | 0 |
| symbol:DUMMYABFRL | KEEP_PLACEHOLDER (#5) | PLACEHOLDER | 0 |
| symbol:DUMMYSIEMS | KEEP_PLACEHOLDER (#6) | PLACEHOLDER | 0 |
| symbol:GSPL | KEEP_SEPARATE (#12) | HISTORICAL_INSTRUMENT | 3 |
| symbol:HEXAWARE | NO_SUCCESSOR (#13) | HISTORICAL_INSTRUMENT | 3 |
| symbol:MINDTREE | NO_SUCCESSOR (#14) | COMPLETE_EXISTING_INSTRUMENT | 2 |
| symbol:NESTLEIND | SET_EFFECTIVE_DATE (#15) | BLOCKED_IDENTITY_MODEL [BLOCKED] | 0 |
| symbol:PEL | KEEP_SEPARATE (#16) | HISTORICAL_INSTRUMENT | 3 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:DUMMYABFRL:MID100:2025-05-22 | RECONSTRUCTION_CORRECT (#7) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:DUMMYSIEMS:NEXT50:2025-04-07 | RECONSTRUCTION_CORRECT (#9) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:CENTRALBK:MID100:2024-09-30 | PARSER_ERROR (#17) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_EXCLUDED_BUT_MEMBER_AFTER:IDEA:MID100:2024-09-30 | PARSER_ERROR (#19) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:IREDA:MID100:2024-03-28 | PARSER_ERROR (#21) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:DUMMYABFRL:N200x:2025-05-22 | RECONSTRUCTION_CORRECT (#8) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:DUMMYSIEMS:N200x:2025-04-07 | RECONSTRUCTION_CORRECT (#10) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:CENTRALBK:N200x:2024-09-30 | PARSER_ERROR (#18) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_EXCLUDED_BUT_MEMBER_AFTER:IDEA:N200x:2024-09-30 | PARSER_ERROR (#20) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:IREDA:N200x:2024-03-28 | PARSER_ERROR (#22) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:TATAMTRDVR:N200x:2023-09-29 | RECONSTRUCTION_CORRECT (#23) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:DUMMYSIEMS:N100x:2025-04-07 | RECONSTRUCTION_CORRECT (#11) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:WALK_INCLUDED_BUT_NOT_MEMBER_AFTER:TATAMTRDVR:N100x:2023-09-29 | RECONSTRUCTION_CORRECT (#24) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:SNAPSHOT_MISMATCH_BLOCK:ITCHOTELS:N200: | PARSER_ERROR (#27) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:SNAPSHOT_MISMATCH_BLOCK:JIOFIN:N200: | CORRECT_DATE (#25) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:SNAPSHOT_MISMATCH_BLOCK:NESTLEIND:N200: | RECONSTRUCTION_CORRECT (#26) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |
| membership:SNAPSHOT_MISMATCH_BLOCK:BSE:N200: | CORRECT_DATE (#28) | NO_WRITE_REFLECTED_IN_RECONSTRUCTION | 0 |

## Reading notes

- `listed_on` is proposed as NULL everywhere: a listing date is a verified fact. The first and last date in our archive are stored separately as `first_observed_on` / `last_traded_on`.
- Alias `valid_from` / `valid_to` carry a basis (`FIRST_OBSERVED`, `LAST_OBSERVED`, `EVIDENCED`): an archive boundary is a floor for resolution, never a claim about when a symbol began or ended. `delisted_on` is set only where a primary document states it (MINDTREE, HEXAWARE).
- ISINs are the ones seen in our own exchange files for the symbol; none was checked against NSDL/CDSL.
- End dates are exclusive: `valid_to` / `delisted_on` is the first day the security no longer trades (last session + 1).
- Successors and relistings are `corporate_action_relationship` rows (migration 024): typed, effective-dated, with an optional ratio, `known_at` (empty: no announcement date is recorded yet) and evidence. They are never aliases.
- NESTLEIND is BLOCKED: see its section for the dependent rows and the plan that needs your approval first.
- MINDTREE and HEXAWARE were recorded with the 'no successor' option only to capture the last day; the successor facts above come from the decision notes.
- Applying any of this changes which membership exceptions clear only as shown in dry_run.md; it does not by itself make the Nifty 200 point-in-time universe ready.

## Writes proposed per item

### symbol:ABIRLANUVO (HISTORICAL_INSTRUMENT)
ABIRLANUVO stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "ABIRLANUVO", "isin": "INE069A01017", "status": "delisted", "listed_on": null, "first_observed_on": "2005-12-07", "last_traded_on": "2017-07-04", "delisted_on": null}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "ABIRLANUVO", "valid_from": "2005-12-07", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2017-07-05", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "AMALGAMATED_INTO", "source_instrument_id": "<new>", "target_symbol": "GRASIM", "appointed_date": null, "effective_date": "2017-07-01", "ratio_num": 15, "ratio_den": 10, "known_at": null, "evidence": ["NSE Indices press release 2017-04-27 (https://www.niftyindices.com/Press_Release/ind_prs27042017.pdf), section 10 NIFTY 200: ABIRLANUVO and GRASIM excluded, effective 2017-05-26 (close 2017-05-25). Grasim press releases: ABNL merged into Grasim effective 2017-07-01, record date 2017-07-06, 15 Grasim : 10 ABNL; financial-services demerger into Aditya Birla Capital effective 2017-07-04.", "Grasim disclosures: 15 Grasim shares per 10 ABNL; not an alias to ABCAPITAL"], "verification_status": "PROVISIONAL", "review_decision_id": 1}`

### symbol:BHARATFIN (HISTORICAL_INSTRUMENT)
BHARATFIN stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "BHARATFIN", "isin": "INE180K01011", "status": "delisted", "listed_on": null, "first_observed_on": "2016-07-01", "last_traded_on": "2019-07-02", "delisted_on": null}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "BHARATFIN", "valid_from": "2016-07-01", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2019-07-03", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "AMALGAMATED_INTO", "source_instrument_id": "<new>", "target_symbol": "INDUSINDBK", "appointed_date": null, "effective_date": "2019-07-04", "ratio_num": 639, "ratio_den": 1000, "known_at": null, "evidence": ["NSE Indices press release Dec 2018 (https://www.niftyindices.com/Press_Release/ind_prs14122018.pdf, read in full): BHARATFIN excluded from several indices effective 2018-12-28 (close 2018-12-27) for the scheme of amalgamation of Bharat Financial Inclusion Ltd into IndusInd Bank Ltd. Our exchange files: ISIN INE180K01011, 2016-07-01..2019-07-02. IndusInd Bank announcement: merger effective 2019-07-04, 639 IndusInd : 1000 BFIL.", "IndusInd Bank announcement (effective date and ratio not re-read from the primary page)"], "verification_status": "PROVISIONAL", "review_decision_id": 2}`

### symbol:DALMIABHA (HISTORICAL_INSTRUMENT)
DALMIABHA stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "DALMIABHA", "isin": "INE439L01019", "status": "delisted", "listed_on": null, "first_observed_on": "2013-01-09", "last_traded_on": "2018-11-28", "delisted_on": null}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "DALMIABHA", "valid_from": "2013-01-09", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2018-11-29", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "AMALGAMATED_INTO", "source_instrument_id": "<new>", "target_symbol": "DALBHARAT", "appointed_date": null, "effective_date": "2019-01-09", "ratio_num": null, "ratio_den": null, "known_at": null, "evidence": ["Dalmia Bharat Annual Report 2017-18 (https://www.dalmiabharat.com/wp-content/uploads/2020/02/Dalmia-Bharat-AR2017-18.pdf, read): erstwhile DBL = NSE DALMIABHA, BSE 533309, ISIN INE439L01019, dissolved without winding up under Scheme B; Odisha Cement Ltd (OCL, to be renamed Dalmia Bharat Ltd) issues shares to DBL holders at 2:1. Annual Report 2018-19 (https://www.bseindia.com/bseplus/AnnualReport/542216/5422160319.pdf, read): shares allotted 2019-01-09, trading from 2019-01-25; name change Odisha Cement -> Dalmia Bharat Ltd effective 2019-04-15.", "scheme of arrangement into Odisha Cement (renamed Dalmia Bharat 2019-04-15); the annual report prints '2:1' without its direction, so no ratio is stored"], "verification_status": "PROVISIONAL", "review_decision_id": 3}`

### symbol:GSPL (HISTORICAL_INSTRUMENT)
GSPL stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "GSPL", "isin": "INE246F01010", "status": "delisted", "listed_on": null, "first_observed_on": "2006-02-16", "last_traded_on": "2026-05-11", "delisted_on": null}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "GSPL", "valid_from": "2006-02-16", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2026-05-12", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "AMALGAMATED_INTO", "source_instrument_id": "<new>", "target_symbol": "GUJENERGY", "appointed_date": null, "effective_date": "2026-05-01", "ratio_num": 10, "ratio_den": 13, "known_at": null, "evidence": ["NSE Indices press release 2026-05-04 (https://www.niftyindices.com/Press_Release/ind_prs04052026.pdf, read): GSPL (Gujarat State Petronet Ltd.) excluded from Nifty 500, Smallcap 250, MidSmallcap 400, Total Market and others effective 2026-05-12 (close 2026-05-11) on account of the scheme of amalgamation of Gujarat State Petronet Ltd. into Gujarat Gas Ltd. Company results filings on NSE (read): .../ixbrl/INTEGRATED_FILING_INDAS_165371_01062026162832_iXBRL_WEB.html and ..._210488_05112026181948_iXBRL_WEB.html: amalgamation of GSPC, GSPL and GEL with Gujarat Gas Ltd, appointed date 2024-04-01, scheme effective 2026-05-01; Gujarat Gas Ltd is now Gujarat Energy Ltd, ISIN INE844O01030, NSE symbol GUJENERGY (GUJGASLTD in the Jun-2026 filing).", "NSE results filings: scheme effective 2026-05-01; ratio 10 Gujarat Gas per 13 GSPL from search results"], "verification_status": "PROVISIONAL", "review_decision_id": 12}`

### symbol:HEXAWARE (HISTORICAL_INSTRUMENT)
HEXAWARE stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "HEXAWARE", "isin": "INE093A01033", "status": "delisted", "listed_on": null, "first_observed_on": "2002-06-14", "last_traded_on": "2020-10-30", "delisted_on": "2020-11-09"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "HEXAWARE", "valid_from": "2002-06-14", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2020-10-31", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "SAME_ISSUER_NEW_INSTRUMENT", "source_instrument_id": "<new>", "target_symbol": "HEXT", "appointed_date": null, "effective_date": "2025-02-19", "ratio_num": null, "ratio_den": null, "known_at": null, "evidence": ["Hexaware delisting Exit Offer FAQs (https://hexaware.com/wp-content/uploads/2020/07/Exit-Offer-FAQs.pdf, read): trading discontinued with effect from 2020-11-02, NSE/BSE delisting date 2020-11-09. NSE circular NSE/CML/66715 (2025-02-18, https://nsearchives.nseindia.com/content/circulars/CML66715.pdf, read): new listing of Hexaware Technologies Limited under symbol HEXT, ISIN INE093A01041 (IPO). Our exchange files: HEXAWARE, ISIN INE093A01033, 2002-06-14..2020-10-30.", "NSE circular CML66715: same issuer relisted by IPO as a new security"], "verification_status": "PROVISIONAL", "review_decision_id": 13}`

### symbol:MINDTREE (COMPLETE_EXISTING_INSTRUMENT)
MINDTREE stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- UPDATE instrument: `{"instrument_id": 2642, "isin": "INE018I01017"}`
- INSERT corporate_action_relationship: `{"relationship_type": "AMALGAMATED_INTO", "source_instrument_id": 2642, "target_symbol": "LTIM", "appointed_date": null, "effective_date": "2022-11-14", "ratio_num": 73, "ratio_den": 100, "known_at": null, "evidence": ["NSE circular NSE/CML/54461 (2022-11-16, https://archives.nseindia.com/content/circulars/CML54461.pdf, read): Mindtree Limited, symbol MINDTREE, EQ, suspended from trading w.e.f. 2022-11-23 (closing hours of 2022-11-22), reason Scheme of Amalgamation. LTI letter 2022-11-15 (nsearchives LTI_15112022175430_Intimationofchangeofname.pdf, read): scheme of amalgamation between Larsen & Toubro Infotech (amalgamated company) and Mindtree (amalgamating company); LTI renamed LTIMindtree Limited w.e.f. 2022-11-15. NSE circular NSE/CML/54604 (2022-11-25, read): symbol LTI -> LTIM w.e.f. 2022-12-05.", "L&T Infotech scheme: effective date and ratio from search results, not a primary filing"], "verification_status": "PROVISIONAL", "review_decision_id": 14}`

### symbol:NESTLEIND (BLOCKED_IDENTITY_MODEL)
NESTLEIND: two ISIN identities linked by the split on 2024-01-05: BLOCKED until the overlap with instrument 1589 is resolved

- BLOCKER: instrument 1589 (new ISIN) already owns 107 bars before 2024-01-05 that traded under the old ISIN, 43 corporate actions and 63 release rows
- BLOCKER: its alias starts before the change date: two aliases of one symbol may not overlap (enforced by migration 024)
- BLOCKER: downstream readers (adjusted bars, membership comparison) must follow a SAME_ISSUER_ISIN_CHANGE relationship before any row is moved
- BLOCKER: decision needed: confirm that the old ISIN is a separate instrument that owns observations up to the day before the change
- PLAN IF APPROVED (1): INSERT instrument (old ISIN INE239A01016), first_observed_on 2010-01-08, last_traded_on = day before 2024-01-05, listed_on NULL
- PLAN IF APPROVED (2): INSERT alias NESTLEIND -> old instrument, valid_to 2024-01-05 (EVIDENCED: NSE circular CML60084)
- PLAN IF APPROVED (3): MOVE bars, corporate actions and release rows dated before 2024-01-05 from instrument 1589 to the old instrument, with pre/post counts and a duplicate check
- PLAN IF APPROVED (4): UPDATE alias of instrument 1589: valid_from 2024-01-05 (EVIDENCED)
- PLAN IF APPROVED (5): INSERT corporate_action_relationship SAME_ISSUER_ISIN_CHANGE old -> new, effective_date 2024-01-05
- PLAN IF APPROVED (6): make the adjusted-bars reader and the membership comparison follow that relationship

### symbol:PEL (HISTORICAL_INSTRUMENT)
PEL stays its own historical instrument; any successor is an effective-dated relationship, not an alias

- INSERT instrument: `{"symbol": "PEL", "isin": "INE140A01024", "status": "delisted", "listed_on": null, "first_observed_on": "2012-09-21", "last_traded_on": "2025-09-22", "delisted_on": null}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "PEL", "valid_from": "2012-09-21", "valid_from_basis": "FIRST_OBSERVED", "valid_to": "2025-09-23", "valid_to_basis": "LAST_OBSERVED"}`
- INSERT corporate_action_relationship: `{"relationship_type": "MERGED_INTO", "source_instrument_id": "<new>", "target_symbol": "PIRAMALFIN", "appointed_date": null, "effective_date": "2025-09-16", "ratio_num": null, "ratio_den": null, "known_at": null, "evidence": ["Piramal Enterprises filing 2025-09-16 (https://www.piramalenterprises.com/Assets/download/CompositeArrangement/Regulations_30_and_51_Disclosure_Effective_Date_PEL_s.pdf, read): Scheme of Merger effective 2025-09-16; PEL merged with Piramal Finance Limited (PFL) and dissolved without being wound up. Filing 2025-09-17 (PEL_Regulations_51_And_60_Disclosure_Signed.pdf, read): Record Date 2025-09-23. Piramal Finance letter 2025-11-04 (PFL-SE-Listing-sd.pdf, read): PFL equity shares issued to PEL shareholders commence trading 2025-11-07. Our exchange files: PEL, ISIN INE140A01024, last session 2025-09-22.", "PEL filing of 2025-09-16 (1:1 ratio not verified, so not stored)"], "verification_status": "PROVISIONAL", "review_decision_id": 16}`


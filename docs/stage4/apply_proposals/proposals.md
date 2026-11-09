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
| symbol:NESTLEIND | SET_EFFECTIVE_DATE (#15) | SAME_ISSUER_ISIN_CHANGE | 3 |
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

- `listed_on` in a proposed instrument is the FIRST DATE IN OUR EXCHANGE-FILE ARCHIVE, not necessarily the true listing date.
- ISINs are the ones seen in our own exchange files for the symbol; none was checked against NSDL/CDSL.
- End dates are exclusive: `valid_to` / `delisted_on` is the first day the security no longer trades (last session + 1).
- 'successor' and 'continuity' records have NO table yet: they are corporate-action facts, never aliases. A schema decision is needed before they can be applied.
- MINDTREE and HEXAWARE were recorded with the 'no successor' option only to capture the last day; the successor facts above come from the decision notes.
- Applying any of this changes which membership exceptions clear only as shown in dry_run.md; it does not by itself make the Nifty 200 point-in-time universe ready.

## Writes proposed per item

### symbol:ABIRLANUVO (HISTORICAL_INSTRUMENT)
ABIRLANUVO stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "ABIRLANUVO", "isin": "INE069A01017", "status": "delisted", "listed_on": "2005-12-07", "delisted_on": "2017-07-05"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "ABIRLANUVO", "valid_from": "2005-12-07", "valid_to": "2017-07-05"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "GRASIM", "effective": "2017-07-01", "basis": "amalgamation into Grasim (decision note; not an alias to ABCAPITAL)", "alias": false}`

### symbol:BHARATFIN (HISTORICAL_INSTRUMENT)
BHARATFIN stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "BHARATFIN", "isin": "INE180K01011", "status": "delisted", "listed_on": "2016-07-01", "delisted_on": "2019-07-03"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "BHARATFIN", "valid_from": "2016-07-01", "valid_to": "2019-07-03"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "INDUSINDBK", "effective": "2019-07-04", "basis": "amalgamation into IndusInd Bank (effective date from the bank's announcement)", "alias": false}`

### symbol:DALMIABHA (HISTORICAL_INSTRUMENT)
DALMIABHA stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "DALMIABHA", "isin": "INE439L01019", "status": "delisted", "listed_on": "2013-01-09", "delisted_on": "2018-11-29"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "DALMIABHA", "valid_from": "2013-01-09", "valid_to": "2018-11-29"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "DALBHARAT", "effective": "2019-01-09", "basis": "scheme of arrangement; shares of Odisha Cement (renamed Dalmia Bharat 2019-04-15) allotted", "alias": false}`

### symbol:GSPL (HISTORICAL_INSTRUMENT)
GSPL stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "GSPL", "isin": "INE246F01010", "status": "delisted", "listed_on": "2006-02-16", "delisted_on": "2026-05-12"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "GSPL", "valid_from": "2006-02-16", "valid_to": "2026-05-12"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "GUJENERGY", "effective": "2026-05-01", "basis": "amalgamation into Gujarat Gas, now Gujarat Energy (scheme effective 2026-05-01)", "alias": false}`

### symbol:HEXAWARE (HISTORICAL_INSTRUMENT)
HEXAWARE stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "HEXAWARE", "isin": "INE093A01033", "status": "delisted", "listed_on": "2002-06-14", "delisted_on": "2020-10-31"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "HEXAWARE", "valid_from": "2002-06-14", "valid_to": "2020-10-31"}`
- RECORD (no table yet) continuity: `{"kind": "SAME_ISSUER_NEW_INSTRUMENT", "successor_symbol": "HEXT", "effective": "2025-02-19", "basis": "same issuer relisted by IPO as a new security", "alias": false}`

### symbol:MINDTREE (COMPLETE_EXISTING_INSTRUMENT)
MINDTREE stays its own historical instrument; successor is a corporate-action fact, not an alias

- UPDATE instrument: `{"instrument_id": 2642, "isin": "INE018I01017"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "LTIM", "effective": "2022-11-14", "basis": "amalgamation into L&T Infotech, now LTIMindtree", "alias": false}`

### symbol:NESTLEIND (SAME_ISSUER_ISIN_CHANGE)
keep two ISIN identities for NESTLEIND, linked by the split on 2024-01-05

- INSERT instrument: `{"symbol": "NESTLEIND", "isin": "INE239A01016", "status": "delisted", "listed_on": "2010-01-08", "delisted_on": "2024-01-05", "note": "old-ISIN identity of the same issuer"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "NESTLEIND", "valid_from": "2010-01-08", "valid_to": "2024-01-05"}`
- RECORD (no table yet) continuity: `{"kind": "SAME_ISSUER_ISIN_CHANGE", "old_isin": "INE239A01016", "new_instrument_id": 1589, "effective": "2024-01-05", "cause": "10:1 face-value split"}`
- CAVEAT: instrument 1589 already has an alias for NESTLEIND starting before 2024-01-05: resolve the overlap (its bars before 2024-01-05 traded under the old ISIN)

### symbol:PEL (HISTORICAL_INSTRUMENT)
PEL stays its own historical instrument; successor is a corporate-action fact, not an alias

- INSERT instrument: `{"symbol": "PEL", "isin": "INE140A01024", "status": "delisted", "listed_on": "2012-09-21", "delisted_on": "2025-09-23"}`
- INSERT instrument_alias: `{"instrument_id": "<new>", "source": "nse", "source_symbol": "PEL", "valid_from": "2012-09-21", "valid_to": "2025-09-23"}`
- RECORD (no table yet) successor: `{"kind": "AMALGAMATED_INTO", "successor_symbol": "PIRAMALFIN", "effective": "2025-09-16", "basis": "merger into Piramal Finance Ltd (filing of 2025-09-16)", "alias": false}`


# exchange_derived_gap_era_demergers_2026-11-15.json: DRY RUN (rolled back; nothing written)

- config sha256 `b40b2f73df3466b1467f3ad4d26cf827409f4d8fe1163db496d043af026061a6`; method exchange_adjusted_price, status provisional, exchange_adjusted_price/1
- formula: factor = base_price / prev_close, base_price = ex-date OPEN (special pre-open session settlement) in the NSE bhavcopy, prev_close = previous session's close

| symbol | check | result | detail |
|---|---|---|---|
| NMDC | stored bhavcopy SHA-256 equals the config | PASS | b5410e9afb641b06 |
| NMDC | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close, OPEN_PRICE = base price | PASS | NMDC 27-Oct-2022 open 92.25 prev 130.75 |
| NMDC | database previous close equals the exchange file | PASS | 130.75 |
| NMDC | a new row was appended and is now the latest | PASS | id 2892 |
| NMDC | factor = exchange_adjusted_price formula at full precision | PASS | 0.7055449330783938814531548757 |
| NMDC | status provisional, no official source claimed | PASS |  |
| NMDC | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| NMDC | calculation inputs stored apart from the evidence | PASS |  |
| NMDC | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.791351 |
| NMDC | strict: still unresolved (provisional is not verified) | PASS |  |
| NMDC | research: applies the new factor, flagged provisional | PASS |  |
| NMDC | note from resolve() | PASS | factor 0.7055 differs from the observed ex-date move 0.2237 |
| MOTHERSON | stored bhavcopy SHA-256 equals the config | PASS | 5e128ff2f1d1e4ad |
| MOTHERSON | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close, OPEN_PRICE = base price | PASS | MOTHERSUMI 14-Jan-2022 open 194.95 prev 234.80 |
| MOTHERSON | database previous close equals the exchange file | PASS | 234.80 |
| MOTHERSON | a new row was appended and is now the latest | PASS | id 2893 |
| MOTHERSON | factor = exchange_adjusted_price formula at full precision | PASS | 0.8302810902896081771720613288 |
| MOTHERSON | status provisional, no official source claimed | PASS |  |
| MOTHERSON | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| MOTHERSON | calculation inputs stored apart from the evidence | PASS |  |
| MOTHERSON | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.790868 |
| MOTHERSON | strict: still unresolved (provisional is not verified) | PASS |  |
| MOTHERSON | research: applies the new factor, flagged provisional | PASS |  |
| MOTHERSON | note from resolve() | PASS | factor 0.8303 differs from the observed ex-date move 0.3512 |
| GMRAIRPORT | stored bhavcopy SHA-256 equals the config | PASS | 2fd41cee284cabf6 |
| GMRAIRPORT | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close, OPEN_PRICE = base price | PASS | GMRINFRA 11-Jan-2022 open 43.75 prev 48.45 |
| GMRAIRPORT | database previous close equals the exchange file | PASS | 48.45 |
| GMRAIRPORT | a new row was appended and is now the latest | PASS | id 2894 |
| GMRAIRPORT | factor = exchange_adjusted_price formula at full precision | PASS | 0.9029927760577915376676986584 |
| GMRAIRPORT | status provisional, no official source claimed | PASS |  |
| GMRAIRPORT | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| GMRAIRPORT | calculation inputs stored apart from the evidence | PASS |  |
| GMRAIRPORT | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.927671 |
| GMRAIRPORT | strict: still unresolved (provisional is not verified) | PASS |  |
| GMRAIRPORT | research: applies the new factor, flagged provisional | PASS |  |
| ABB | stored bhavcopy SHA-256 equals the config | PASS | 8c4cbfbc6a5a9f5c |
| ABB | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close, OPEN_PRICE = base price | PASS | ABB 20-Dec-2019 open 1324.00 prev 1476.00 |
| ABB | database previous close equals the exchange file | PASS | 1476.00 |
| ABB | a new row was appended and is now the latest | PASS | id 2895 |
| ABB | factor = exchange_adjusted_price formula at full precision | PASS | 0.8970189701897018970189701897 |
| ABB | status provisional, no official source claimed | PASS |  |
| ABB | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| ABB | calculation inputs stored apart from the evidence | PASS |  |
| ABB | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.854386 |
| ABB | strict: still unresolved (provisional is not verified) | PASS |  |
| ABB | research: applies the new factor, flagged provisional | PASS |  |
| ALL | dry run: action_resolution unchanged after the rollback | PASS | (2846, 2891) -> (2846, 2891) |

**Result: PASS**

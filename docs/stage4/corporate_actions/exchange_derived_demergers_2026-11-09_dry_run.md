# exchange_derived_demergers_2026-11-09.json: DRY RUN (rolled back; nothing written)

- config sha256 `f901e73710446ae57564a38769e3bef026f8acc417554f26fa3f6fc00226354f`; method exchange_adjusted_price, status provisional, exchange_adjusted_price/1
- formula: factor = base_price / prev_close, base_price = ex-date OPEN (special pre-open session settlement) in the NSE bhavcopy, prev_close = previous session's close

| symbol | check | result | detail |
|---|---|---|---|
| RELIANCE | stored bhavcopy SHA-256 equals the config | PASS | 60afba4661bc75fd |
| RELIANCE | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | RELIANCE 20-Jul-2023 open 2580.00 prev 2841.85 |
| RELIANCE | database previous close equals the exchange file | PASS | 2841.85 |
| RELIANCE | a new row was appended and is now the latest | PASS | id 49 |
| RELIANCE | factor = base / previous close at full precision | PASS | 0.9078593169942115171455214033 |
| RELIANCE | status provisional, no official source claimed | PASS |  |
| RELIANCE | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| RELIANCE | evidence stored with the calculation inputs kept apart | PASS |  |
| RELIANCE | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.919886 |
| RELIANCE | strict: still unresolved (provisional is not verified) | PASS |  |
| RELIANCE | research: applies the new factor, flagged provisional | PASS |  |
| ITC | stored bhavcopy SHA-256 equals the config | PASS | 9dc1eb315195c68b |
| ITC | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | ITC 06-Jan-2025 open 455.60 prev 481.60 |
| ITC | database previous close equals the exchange file | PASS | 481.60 |
| ITC | a new row was appended and is now the latest | PASS | id 50 |
| ITC | factor = base / previous close at full precision | PASS | 0.9460132890365448504983388704 |
| ITC | status provisional, no official source claimed | PASS |  |
| ITC | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| ITC | evidence stored with the calculation inputs kept apart | PASS |  |
| ITC | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.944959 |
| ITC | strict: still unresolved (provisional is not verified) | PASS |  |
| ITC | research: applies the new factor, flagged provisional | PASS |  |
| SIEMENS | stored bhavcopy SHA-256 equals the config | PASS | 9a5b9c52a10cf322 |
| SIEMENS | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | SIEMENS 07-Apr-2025 open 2450.00 prev 4928.15 |
| SIEMENS | database previous close equals the exchange file | PASS | 4928.15 |
| SIEMENS | a new row was appended and is now the latest | PASS | id 51 |
| SIEMENS | factor = base / previous close at full precision | PASS | 0.4971439586863224536590809939 |
| SIEMENS | status provisional, no official source claimed | PASS |  |
| SIEMENS | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| SIEMENS | evidence stored with the calculation inputs kept apart | PASS |  |
| SIEMENS | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.590556 |
| SIEMENS | strict: still unresolved (provisional is not verified) | PASS |  |
| SIEMENS | research: applies the new factor, flagged provisional | PASS |  |
| TMPV | stored bhavcopy SHA-256 equals the config | PASS | d72fcbad87c23165 |
| TMPV | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | TATAMOTORS 14-Oct-2025 open 400.00 prev 660.75 |
| TMPV | database previous close equals the exchange file | PASS | 660.75 |
| TMPV | a new row was appended and is now the latest | PASS | id 52 |
| TMPV | factor = base / previous close at full precision | PASS | 0.6053726825576995838062807416 |
| TMPV | status provisional, no official source claimed | PASS |  |
| TMPV | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| TMPV | evidence stored with the calculation inputs kept apart | PASS |  |
| TMPV | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.602534 |
| TMPV | strict: still unresolved (provisional is not verified) | PASS |  |
| TMPV | research: applies the new factor, flagged provisional | PASS |  |
| HINDUNILVR | stored bhavcopy SHA-256 equals the config | PASS | 878cc00f7f71b39d |
| HINDUNILVR | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | HINDUNILVR 05-Dec-2025 open 2422.00 prev 2462.20 |
| HINDUNILVR | database previous close equals the exchange file | PASS | 2462.20 |
| HINDUNILVR | a new row was appended and is now the latest | PASS | id 53 |
| HINDUNILVR | factor = base / previous close at full precision | PASS | 0.9836731378442043700755421980 |
| HINDUNILVR | status provisional, no official source claimed | PASS |  |
| HINDUNILVR | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| HINDUNILVR | evidence stored with the calculation inputs kept apart | PASS |  |
| HINDUNILVR | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.946812 |
| HINDUNILVR | strict: still unresolved (provisional is not verified) | PASS |  |
| HINDUNILVR | research: applies the new factor, flagged provisional | PASS |  |
| VEDL | stored bhavcopy SHA-256 equals the config | PASS | 215b10ba246b88b6 |
| VEDL | bhavcopy row: OPEN_PRICE = base price, PREV_CLOSE = expected previous close | PASS | VEDL 30-Apr-2026 open 289.50 prev 773.60 |
| VEDL | database previous close equals the exchange file | PASS | 773.60 |
| VEDL | a new row was appended and is now the latest | PASS | id 54 |
| VEDL | factor = base / previous close at full precision | PASS | 0.3742244053774560496380558428 |
| VEDL | status provisional, no official source claimed | PASS |  |
| VEDL | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| VEDL | evidence stored with the calculation inputs kept apart | PASS |  |
| VEDL | the earlier estimate is kept as history, superseded | PASS | earlier: gap 0.354834 |
| VEDL | strict: still unresolved (provisional is not verified) | PASS |  |
| VEDL | research: applies the new factor, flagged provisional | PASS |  |
| ALL | dry run: action_resolution unchanged after the rollback | PASS | (36, 36) -> (36, 36) |

**Result: PASS**

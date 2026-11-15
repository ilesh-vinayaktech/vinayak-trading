# pel_demerger_2022-08-30_recorded_2026-11-15.json: APPLY

- config sha256 `bf8115f049ed3b29c765bd025b09a88e9f29b876383086d082b213cc7071c628`; method exchange_adjusted_price, status provisional, exchange_adjusted_price/1
- formula: factor = base_price / prev_close, base_price = ex-date OPEN (special pre-open session settlement) in the NSE bhavcopy, prev_close = previous session's close

| symbol | check | result | detail |
|---|---|---|---|
| PEL | stored bhavcopy SHA-256 equals the config | PASS | 209b1e2e0335813c |
| PEL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close, OPEN_PRICE = base price | PASS | PEL 30-Aug-2022 open 1055.05 prev 1926.50 |
| PEL | database previous close equals the exchange file | PASS | 1926.50 |
| PEL | a new row was appended and is now the latest | PASS | id 2883 |
| PEL | factor = exchange_adjusted_price formula at full precision | PASS | 0.5476511808980015572281339216 |
| PEL | status provisional, no official source claimed | PASS |  |
| PEL | evidence class PROVISIONAL_EXCHANGE_DERIVED | PASS |  |
| PEL | calculation inputs stored apart from the evidence | PASS |  |
| PEL | the earlier estimate is kept as history, superseded | PASS | none |
| PEL | strict: still unresolved (provisional is not verified) | PASS |  |
| PEL | research: applies the new factor, flagged provisional | PASS |  |
| ALL | rows appended | PASS | (2841, 2882) -> (2842, 2883) |

**Result: PASS**

# pel_rights_2019-12-30_recorded_2026-11-15.json: DRY RUN (rolled back; nothing written)

- config sha256 `f1f3627f04296b2bbcd624eef8fdaa041d835bbf9a94d3cb0929b6f1b1381d73`; method rights, status provisional, rights_terp_full_issue_price/1
- formula: factor = TERP / P, TERP = (B x P + A x S) / (A + B); A new shares, B held, S the full issue price (face value + premium), P the previous cum-rights close (= ex-date PREV_CLOSE in the NSE bhavcopy)

| symbol | check | result | detail |
|---|---|---|---|
| PEL | stored bhavcopy SHA-256 equals the config | PASS | 40071d699a638cf6 |
| PEL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | PEL 30-Dec-2019 open 1618.00 prev 1632.90 |
| PEL | database previous close equals the exchange file | PASS | 1632.90 |
| PEL | a new row was appended and is now the latest | PASS | id 2880 |
| PEL | factor = rights formula at full precision | PASS | 0.9761428238234286213146431815 |
| PEL | status provisional, no official source claimed | PASS |  |
| PEL | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| PEL | calculation inputs stored apart from the evidence | PASS |  |
| PEL | the earlier estimate is kept as history, superseded | PASS | none |
| PEL | strict: still unresolved (provisional is not verified) | PASS |  |
| PEL | research: applies the new factor, flagged provisional | PASS |  |
| ALL | dry run: action_resolution unchanged after the rollback | PASS | (2840, 2879) -> (2840, 2879) |

**Result: PASS**

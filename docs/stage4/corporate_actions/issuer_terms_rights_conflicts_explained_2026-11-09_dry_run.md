# issuer_terms_rights_conflicts_explained_2026-11-09.json: DRY RUN (rolled back; nothing written)

- config sha256 `e0f14d45ce6fe8268308962ae820d89d12b19c799b7846bff67c953f6bdaef26`; method rights, status provisional, rights_terp_full_issue_price/1
- formula: factor = TERP / P, TERP = (B x P + A x S) / (A + B); A new shares, B held, S the full issue price (face value + premium), P the previous cum-rights close (= ex-date PREV_CLOSE in the NSE bhavcopy)

| symbol | check | result | detail |
|---|---|---|---|
| TATACONSUM | stored bhavcopy SHA-256 equals the config | PASS | b831ab462ee02109 |
| TATACONSUM | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | TATACONSUM 26-Jul-2024 open 1216.05 prev 1223.60 |
| TATACONSUM | database previous close equals the exchange file | PASS | 1223.60 |
| TATACONSUM | a new row was appended and is now the latest | PASS | id 85 |
| TATACONSUM | factor = rights formula at full precision | PASS | 0.9877229305146925284225055394 |
| TATACONSUM | status provisional, no official source claimed | PASS |  |
| TATACONSUM | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| TATACONSUM | calculation inputs stored apart from the evidence | PASS |  |
| TATACONSUM | the earlier estimate is kept as history, superseded | PASS | earlier: rights 0.987723 |
| TATACONSUM | strict: still unresolved (provisional is not verified) | PASS |  |
| TATACONSUM | research: applies the new factor, flagged provisional | PASS |  |
| UPL | stored bhavcopy SHA-256 equals the config | PASS | ed333291256cbf0f |
| UPL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | UPL 26-Nov-2024 open 545.00 prev 568.55 |
| UPL | database previous close equals the exchange file | PASS | 568.55 |
| UPL | a new row was appended and is now the latest | PASS | id 86 |
| UPL | factor = rights formula at full precision | PASS | 0.9592432992309872091773419713 |
| UPL | status provisional, no official source claimed | PASS |  |
| UPL | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| UPL | calculation inputs stored apart from the evidence | PASS |  |
| UPL | the earlier estimate is kept as history, superseded | PASS | earlier: rights 0.959243 |
| UPL | strict: still unresolved (provisional is not verified) | PASS |  |
| UPL | research: applies the new factor, flagged provisional | PASS |  |
| ALL | dry run: action_resolution unchanged after the rollback | PASS | (51, 84) -> (51, 84) |

**Result: PASS**

# issuer_terms_rights_2026-11-09.json: DRY RUN (rolled back; nothing written)

- config sha256 `97991892053caaeca4ba0f84acc4a6f68b55917c7af27f6664e2f93416dbc088`; method rights, status provisional, rights_terp_full_issue_price/1
- formula: factor = TERP / P, TERP = (B x P + A x S) / (A + B); A new shares, B held, S the full issue price (face value + premium), P the previous cum-rights close (= ex-date PREV_CLOSE in the NSE bhavcopy)

| symbol | check | result | detail |
|---|---|---|---|
| RELIANCE | stored bhavcopy SHA-256 equals the config | PASS | 55f4d226421bd9d3 |
| RELIANCE | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | RELIANCE 13-May-2020 open 1527.00 prev 1479.25 |
| RELIANCE | database previous close equals the exchange file | PASS | 1479.25 |
| RELIANCE | a new row was appended and is now the latest | PASS | id 67 |
| RELIANCE | factor = rights formula at full precision | PASS | 0.9906096839614669596079094136 |
| RELIANCE | status provisional, no official source claimed | PASS |  |
| RELIANCE | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| RELIANCE | calculation inputs stored apart from the evidence | PASS |  |
| RELIANCE | the earlier estimate is kept as history, superseded | PASS | none |
| RELIANCE | strict: still unresolved (provisional is not verified) | PASS |  |
| RELIANCE | research: applies the new factor, flagged provisional | PASS |  |
| SHRIRAMFIN | stored bhavcopy SHA-256 equals the config | PASS | c54645249aaf4f06 |
| SHRIRAMFIN | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | SRTRANSFIN 09-Jul-2020 open 748.00 prev 757.90 |
| SHRIRAMFIN | database previous close equals the exchange file | PASS | 757.90 |
| SHRIRAMFIN | a new row was appended and is now the latest | PASS | id 68 |
| SHRIRAMFIN | factor = rights formula at full precision | PASS | 0.9743529079898630972150816002 |
| SHRIRAMFIN | status provisional, no official source claimed | PASS |  |
| SHRIRAMFIN | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| SHRIRAMFIN | calculation inputs stored apart from the evidence | PASS |  |
| SHRIRAMFIN | the earlier estimate is kept as history, superseded | PASS | none |
| SHRIRAMFIN | strict: still unresolved (provisional is not verified) | PASS |  |
| SHRIRAMFIN | research: applies the new factor, flagged provisional | PASS |  |
| LTF | stored bhavcopy SHA-256 equals the config | PASS | 0d95166754967df0 |
| LTF | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | L&TFH 21-Jan-2021 open 97.00 prev 103.85 |
| LTF | database previous close equals the exchange file | PASS | 103.85 |
| LTF | a new row was appended and is now the latest | PASS | id 69 |
| LTF | factor = rights formula at full precision | PASS | 0.9301136994926113847635272767 |
| LTF | status provisional, no official source claimed | PASS |  |
| LTF | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| LTF | calculation inputs stored apart from the evidence | PASS |  |
| LTF | the earlier estimate is kept as history, superseded | PASS | none |
| LTF | strict: still unresolved (provisional is not verified) | PASS |  |
| LTF | research: applies the new factor, flagged provisional | PASS |  |
| BHARTIARTL | stored bhavcopy SHA-256 equals the config | PASS | df4b8964b47c41bd |
| BHARTIARTL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | BHARTIARTL 27-Sep-2021 open 731.00 prev 739.40 |
| BHARTIARTL | database previous close equals the exchange file | PASS | 739.40 |
| BHARTIARTL | a new row was appended and is now the latest | PASS | id 70 |
| BHARTIARTL | factor = rights formula at full precision | PASS | 0.9815706428635830853845460283 |
| BHARTIARTL | status provisional, no official source claimed | PASS |  |
| BHARTIARTL | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| BHARTIARTL | calculation inputs stored apart from the evidence | PASS |  |
| BHARTIARTL | the earlier estimate is kept as history, superseded | PASS | none |
| BHARTIARTL | strict: still unresolved (provisional is not verified) | PASS |  |
| BHARTIARTL | research: applies the new factor, flagged provisional | PASS |  |
| INDHOTEL | stored bhavcopy SHA-256 equals the config | PASS | c955168b53b887c8 |
| INDHOTEL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | INDHOTEL 11-Nov-2021 open 214.00 prev 215.30 |
| INDHOTEL | database previous close equals the exchange file | PASS | 215.30 |
| INDHOTEL | a new row was appended and is now the latest | PASS | id 71 |
| INDHOTEL | factor = rights formula at full precision | PASS | 0.9696702275894101254064096609 |
| INDHOTEL | status provisional, no official source claimed | PASS |  |
| INDHOTEL | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| INDHOTEL | calculation inputs stored apart from the evidence | PASS |  |
| INDHOTEL | the earlier estimate is kept as history, superseded | PASS | none |
| INDHOTEL | strict: still unresolved (provisional is not verified) | PASS |  |
| INDHOTEL | research: applies the new factor, flagged provisional | PASS |  |
| GRASIM | stored bhavcopy SHA-256 equals the config | PASS | 93f25cb682042e43 |
| GRASIM | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | GRASIM 10-Jan-2024 open 2058.80 prev 2064.05 |
| GRASIM | database previous close equals the exchange file | PASS | 2064.05 |
| GRASIM | a new row was appended and is now the latest | PASS | id 72 |
| GRASIM | factor = rights formula at full precision | PASS | 0.9960395365448537610064704852 |
| GRASIM | status provisional, no official source claimed | PASS |  |
| GRASIM | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| GRASIM | calculation inputs stored apart from the evidence | PASS |  |
| GRASIM | the earlier estimate is kept as history, superseded | PASS | none |
| GRASIM | strict: still unresolved (provisional is not verified) | PASS |  |
| GRASIM | research: applies the new factor, flagged provisional | PASS |  |
| TATACONSUM | stored bhavcopy SHA-256 equals the config | PASS | b831ab462ee02109 |
| TATACONSUM | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | TATACONSUM 26-Jul-2024 open 1216.05 prev 1223.60 |
| TATACONSUM | database previous close equals the exchange file | PASS | 1223.60 |
| TATACONSUM | a new row was appended and is now the latest | PASS | id 73 |
| TATACONSUM | factor = rights formula at full precision | PASS | 0.9877229305146925284225055394 |
| TATACONSUM | status provisional, no official source claimed | PASS |  |
| TATACONSUM | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| TATACONSUM | calculation inputs stored apart from the evidence | PASS |  |
| TATACONSUM | the earlier estimate is kept as history, superseded | PASS | none |
| TATACONSUM | strict: still unresolved (provisional is not verified) | PASS |  |
| TATACONSUM | research: applies the new factor, flagged provisional | PASS |  |
| UPL | stored bhavcopy SHA-256 equals the config | PASS | ed333291256cbf0f |
| UPL | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | UPL 26-Nov-2024 open 545.00 prev 568.55 |
| UPL | database previous close equals the exchange file | PASS | 568.55 |
| UPL | a new row was appended and is now the latest | PASS | id 74 |
| UPL | factor = rights formula at full precision | PASS | 0.9592432992309872091773419713 |
| UPL | status provisional, no official source claimed | PASS |  |
| UPL | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| UPL | calculation inputs stored apart from the evidence | PASS |  |
| UPL | the earlier estimate is kept as history, superseded | PASS | none |
| UPL | strict: still unresolved (provisional is not verified) | PASS |  |
| UPL | research: applies the new factor, flagged provisional | PASS |  |
| ADANIENT | stored bhavcopy SHA-256 equals the config | PASS | c8b46755536d96c4 |
| ADANIENT | bhavcopy row on the ex-date: PREV_CLOSE = expected previous close | PASS | ADANIENT 17-Nov-2025 open 2460.00 prev 2516.80 |
| ADANIENT | database previous close equals the exchange file | PASS | 2516.80 |
| ADANIENT | a new row was appended and is now the latest | PASS | id 75 |
| ADANIENT | factor = rights formula at full precision | PASS | 0.9694850603941513032422123331 |
| ADANIENT | status provisional, no official source claimed | PASS |  |
| ADANIENT | evidence class PROVISIONAL_ISSUER_TERMS | PASS |  |
| ADANIENT | calculation inputs stored apart from the evidence | PASS |  |
| ADANIENT | the earlier estimate is kept as history, superseded | PASS | none |
| ADANIENT | strict: still unresolved (provisional is not verified) | PASS |  |
| ADANIENT | research: applies the new factor, flagged provisional | PASS |  |
| ALL | dry run: action_resolution unchanged after the rollback | PASS | (42, 60) -> (42, 60) |

**Result: PASS**

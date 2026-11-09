# Rights issues affecting the research window: TERP proposal (read-only; nothing applied)

factor = TERP / P, TERP = (B x P + A x S) / (A + B), S = the FULL issue price (face value + premium), P = previous cum-rights close.
This equals the exchanges' F&O rights adjustment factor (P - E) / P. No exchange adjusts the cash-market base price for a rights issue
(the bhavcopy PREV_CLOSE on every ex-date is the unadjusted cum close), so there is no exchange base price to take precedence.

| symbol | ex-date | A:B | issue price | P (cum close) | proposed factor | exchange factor found | reproduced | payment |
|---|---|---|---|---|---|---|---|---|
| RELIANCE | 2020-05-13 | 1:15 | 1257 | 1479.25 | 0.990610 | - | n/a | PARTLY PAID: Rs 314.25 on application (25%), balance in two calls; the partly paid shares listed separately |
| SHRIRAMFIN | 2020-07-09 | 3:26 | 570 | 757.90 | 0.974353 | - | n/a | fully paid (Shriram Transport Finance) |
| LTF | 2021-01-21 | 17:74 | 65 | 103.85 | 0.930114 | - | n/a | fully paid (L&T Finance Holdings) |
| BHARTIARTL | 2021-09-27 | 1:14 | 535 | 739.40 | 0.981571 | 0.981571 | yes | PARTLY PAID: Rs 133.75 on application (25%), balance in calls; the partly paid shares listed separately |
| INDHOTEL | 2021-11-11 | 1:9 | 150 | 215.30 | 0.969670 | - | n/a | fully paid |
| SUZLON | 2022-10-03 | 5:21 | 5 | 8.70 | 0.918214 | - | n/a | PARTLY PAID (Re 1 paid on application per a later BSE filing; first and final call Rs 2.50 per the call notice); not an F&O stock then; issue proceeded and closed 1.8x subscribed |
| GRASIM | 2024-01-10 | 6:179 | 1812 | 2064.05 | 0.996040 | 0.996040 | yes | PARTLY PAID: Rs 453 on application, balance Rs 1,359 in calls |
| TATACONSUM | 2024-07-26 | 1:26 | 818 | 1223.60 | 0.987723 | - | n/a | terms say Rs 818 per share; payment structure not confirmed; the exchange worked example used a cum close of 1231.25, which differs from the 25 Jul close 1223.60 in the bhavcopy |
| UPL | 2024-11-26 | 1:8 | 360 | 568.55 | 0.959243 | 0.959243 | yes | PARTLY PAID: Rs 90 on application, balance in calls |
| ADANIENT | 2025-11-17 | 3:25 | 1800 | 2516.80 | 0.969485 | 0.969485 | yes | PARTLY PAID: Rs 900 on application, balance in two calls (record dates 2025-12-23 and 2026-02-13) |

Sources per row (and which were not retrieved) are in `config/proposed/rights_resolutions.json`.

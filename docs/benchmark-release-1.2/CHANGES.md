# Benchmark Release 1.2 - change report against 1.1

Datasets now run to 2026-11-12 (1.1 stopped at 2026-11-06); validations 9-12 cover them. Audit: `docs/benchmark-audit-1.2` (run with `--calendar docs/calendar-evidence/full_ledger.json`).

| finding | 1.1 | 1.2 | evidence |
|---|---|---|---|
| U02 regular session hours | UNRESOLVED (blocked intraday) | RESOLVED | every one of 2,691 days of the stored 1-minute history read: 2,675 ran 09:15-15:30, 15 are listed special sessions, 1 has an extra closing bar; none unexplained (`docs/session-evidence/minute_hours_scan.json`) |
| U03 special-session kinds and hours | UNRESOLVED (blocked intraday) | ACCEPTED_WITH_EVIDENCE | 19 sessions inside the minute history have kind and hours from NSE circulars and/or the minute bars (all circulars agree with the bars); 21 earlier sessions (1999-2015) are marked SPECIAL, owner decision 2026-11-13 |
| U04 weekday calendar | UNRESOLVED | ACCEPTED_WITH_EVIDENCE | every observed weekday has an exchange file; closures inferred from the PREVCLOSE chain, not holiday lists |
| U09 revision behaviour | UNRESOLVED | RESOLVED | 81 stored windows re-requested on 2026-11-13: none differs (`docs/benchmark-evidence/revision_check_2026-11-13.json`) |
| U10 methodology documents | UNRESOLVED | ACCEPTED_WITH_EVIDENCE | 42 editions 2018-2026 from the Internet Archive's copies of the official URLs (`docs/benchmark-evidence/methodology_history.json`); earlier editions not retrievable |

Open: U05, U06, U08, U11, U16 (and U07 accepted before). The gate stays disabled. New this release: intraday research is eligible for all four benchmarks; the gate still needs U05/U11/U16 (Nifty 200 series) or U06/U08/U11/U16 (Nifty 50 gross) decided, and Nifty 50 net can never pass technical validation.

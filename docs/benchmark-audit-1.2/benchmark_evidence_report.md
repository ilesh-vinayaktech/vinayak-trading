# Benchmark evidence report

Cross-index alignment and session-calendar audit. Generated; deterministic for identical inputs. **This report does not enable any benchmark gate.**

## Series

| series | first | last | obs | duplicates | dataset hash | validation | passed | report | covers current data |
|---|---|---|---:|---:|---|---:|---|---|---|
| B1_NIFTY200_GROSS_TRI | 2004-01-01 | 2026-11-12 | 5677 | 0 | `b22029030d91` | 9 | True | 2 | True |
| B2_NIFTY50_GROSS_TRI | 1999-06-30 | 2026-11-12 | 6809 | 0 | `6a5cdc34ac24` | 11 | True | 2 | True |
| B3_NIFTY50_NET_TRI | 2000-01-03 | 2026-11-12 | 6680 | 0 | `18667ecc208e` | 12 | False | 2 | True |
| B4_NIFTY200_PRICE_RETURN | 2004-01-01 | 2026-11-12 | 5677 | 0 | `01da8ae2bdb7` | 10 | True | 2 | True |

Coverage differs by design (Nifty 50 gross 1999-06-30, net 2000-01-03, the others 2004-01-01); those dates are classified COVERAGE differences, not gaps.

## Calendar and evidence

- sessions file sha256 `b531e9079a22`, holiday feed `8903f442b9b3` (years [2026])
- independent trading evidence = bhavcopy: 6808 loaded, 102 not published, quarantined [], range 2019-10-01..2026-11-13
- a benchmark value is never used as evidence that the exchange traded

## Observed dates by outcome

| outcome | dates |
|---|---:|
| BENCHMARK_ONLY_SESSION | 1 |
| CONFIRMED_REGULAR | 6769 |
| CONFIRMED_SPECIAL | 39 |

## Missing values inside each series' coverage

| series | EXPECTED_CLOSED | EXPECTED_CLOSED_INFERRED | EXPECTED_NO_SESSION |
|---|---:|---:|---:|
| B1_NIFTY200_GROSS_TRI | 101 | 216 | 2358 |
| B2_NIFTY50_GROSS_TRI | 101 | 264 | 2824 |
| B3_NIFTY50_NET_TRI | 101 | 259 | 2771 |
| B4_NIFTY200_PRICE_RETURN | 101 | 216 | 2358 |

Confirmed trading sessions without a value (DATA_GAP): 0.

## Discontinuities (>=5% a day)

{'CORROBORATED': 212, 'UNCORROBORATED_SINGLE_SERIES': 2}

## Anomaly overlap (Price vs TRI, Net vs Gross)

- price beats TRI: 395 days; net gains on gross: 41 days
- intersection 0 dates (expected by chance 2.85) -> **NO_OVERLAP_BEYOND_CHANCE**
- magnitude correlation, all common dates: 0.03934756434599174; on the anomaly union: -0.4376204602143617
- dividend ex-date share: price 0.46, net 0.98, all common dates 0.66
- severity LOW: numerical behaviour below 0.01% a day; not a material correctness issue for daily research

## 2022-08-08

resolved: the exchange's own file was recovered (docs/recovery/bhavcopy_2022-08-08.json)

## Historical session hours

every one of the 2691 days in the stored 1-minute history (2016-01-04 to 2026-11-12) was read: 2675 ran 09:15-15:30, 15 are listed special sessions and 1 have one extra closing-price bar; none is unexplained. Before 2016-01-04 only daily data exists, so no intraday research can depend on those hours. Daily benchmark levels do not depend on hours.

## Eligibility (separate states; the gate stays disabled)

| series | state | daily research | intraday research | gate |
|---|---|---|---|---|
| B1_NIFTY200_GROSS_TRI | RESEARCH_ELIGIBLE | True | True | False |
| B2_NIFTY50_GROSS_TRI | RESEARCH_ELIGIBLE | True | True | False |
| B3_NIFTY50_NET_TRI | RESEARCH_ELIGIBLE | True | True | False |
| B4_NIFTY200_PRICE_RETURN | RESEARCH_ELIGIBLE | True | True | False |

Instrument-level research must exclude: no date.

## Unresolved findings

| id | severity | status | title |
|---|---|---|---|
| U01 | INFO | RESOLVED | 2022-08-08 bhavcopy recovered from the spreadsheet NSE served |
| U02 | INFO | RESOLVED | Regular session hours observed on every day of the minute history |
| U03 | MEDIUM | ACCEPTED_WITH_EVIDENCE | Special sessions: every one inside the minute history has its hours; earlier ones are marked SPECIAL |
| U04 | LOW | ACCEPTED_WITH_EVIDENCE | Weekday closures before 2026 are inferred from exchange files, not holiday lists |
| U05 | LOW | UNRESOLVED | Price return exceeds gross TRI by up to 0.005% on some days |
| U06 | LOW | UNRESOLVED | Net TRI gains on gross TRI on 41 days (0.002-0.006%) |
| U07 | LOW | ACCEPTED_WITH_EVIDENCE | 11 net/gross jumps on bonus ex-dates: explained, not numerically reconciled |
| U08 | MEDIUM | UNRESOLVED | Gross and net independence unknown; net is a non-resident institutional measure |
| U09 | INFO | RESOLVED | Revision behaviour of the endpoints: history re-fetched and unchanged |
| U10 | LOW | ACCEPTED_WITH_EVIDENCE | Methodology documents: editions from 2018 to 2026 held |
| U11 | LOW | UNRESOLVED | Factsheet CAGR convention unidentified; Nifty 50 gross since-inception not reproducible |
| U16 | LOW | UNRESOLVED | Large daily moves seen by one series only |

Full machine-readable detail: `benchmark_alignment_report.json`, `session_reconciliation_report.json`, `benchmark_unresolved_findings.json`.

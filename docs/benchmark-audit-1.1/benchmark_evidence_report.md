# Benchmark evidence report

Cross-index alignment and session-calendar audit. Generated; deterministic for identical inputs. **This report does not enable any benchmark gate.**

## Series

| series | first | last | obs | duplicates | dataset hash | validation | passed | report | covers current data |
|---|---|---|---:|---:|---|---:|---|---|---|
| B1_NIFTY200_GROSS_TRI | 2004-01-01 | 2026-11-06 | 5673 | 0 | `8cf2b57a726b` | 6 | True | 2 | True |
| B2_NIFTY50_GROSS_TRI | 1999-06-30 | 2026-11-06 | 6805 | 0 | `85f910ebe88e` | 7 | True | 2 | True |
| B3_NIFTY50_NET_TRI | 2000-01-03 | 2026-11-06 | 6676 | 0 | `d2b9cf96ffd9` | 4 | False | 2 | True |
| B4_NIFTY200_PRICE_RETURN | 2004-01-01 | 2026-11-06 | 5673 | 0 | `f12eb1f3edff` | 8 | True | 2 | True |

Coverage differs by design (Nifty 50 gross 1999-06-30, net 2000-01-03, the others 2004-01-01); those dates are classified COVERAGE differences, not gaps.

## Calendar and evidence

- sessions file sha256 `41067f09929a`, holiday feed `1aff3cd77761` (years [2026])
- independent trading evidence = bhavcopy: 1785 loaded, 100 not published, quarantined [], range 2019-10-01..2026-11-06
- a benchmark value is never used as evidence that the exchange traded

## Observed dates by outcome

| outcome | dates |
|---|---:|
| CONFIRMED_REGULAR | 1753 |
| CONFIRMED_SPECIAL | 32 |
| WEEKDAY_RULE_PROVISIONAL | 5020 |

## Missing values inside each series' coverage

| series | EXPECTED_CLOSED | EXPECTED_NO_SESSION | UNCONFIRMED_NO_VALUE |
|---|---:|---:|---:|
| B1_NIFTY200_GROSS_TRI | 100 | 2357 | 216 |
| B2_NIFTY50_GROSS_TRI | 100 | 2823 | 264 |
| B3_NIFTY50_NET_TRI | 100 | 2770 | 259 |
| B4_NIFTY200_PRICE_RETURN | 100 | 2357 | 216 |

Confirmed trading sessions without a value (DATA_GAP): 0.

## Discontinuities (>=5% a day)

{'CORROBORATED': 212, 'UNCORROBORATED_SINGLE_SERIES': 2}

## Anomaly overlap (Price vs TRI, Net vs Gross)

- price beats TRI: 395 days; net gains on gross: 41 days
- intersection 0 dates (expected by chance 2.86) -> **NO_OVERLAP_BEYOND_CHANCE**
- magnitude correlation, all common dates: 0.03932571510808261; on the anomaly union: -0.4376204602143617
- dividend ex-date share: price 0.08, net 0.93, all common dates 0.40
- severity LOW: numerical behaviour below 0.01% a day; not a material correctness issue for daily research

## 2022-08-08

resolved: the exchange's own file was recovered (docs/recovery/bhavcopy_2022-08-08.json)

## Historical session hours

no historical session hours are held as evidence; every intraday bar visibility decision relies on the current 09:15-15:30 schedule, and special sessions on assumed regular hours. Daily benchmark levels do not depend on hours.

## Eligibility (separate states; the gate stays disabled)

| series | state | daily research | intraday research | gate |
|---|---|---|---|---|
| B1_NIFTY200_GROSS_TRI | RESEARCH_ELIGIBLE | True | False | False |
| B2_NIFTY50_GROSS_TRI | RESEARCH_ELIGIBLE | True | False | False |
| B3_NIFTY50_NET_TRI | RESEARCH_ELIGIBLE | True | False | False |
| B4_NIFTY200_PRICE_RETURN | RESEARCH_ELIGIBLE | True | False | False |

Instrument-level research must exclude: no date.

## Unresolved findings

| id | severity | status | title |
|---|---|---|---|
| U01 | INFO | RESOLVED | 2022-08-08 bhavcopy recovered from the spreadsheet NSE served |
| U02 | HIGH | UNRESOLVED | Historical session hours are not verified |
| U03 | MEDIUM | UNRESOLVED | Special-session kinds are unconfirmed and their hours unknown |
| U04 | MEDIUM | UNRESOLVED | Weekday sessions before the bhavcopy history rest on the calendar rule |
| U05 | LOW | UNRESOLVED | Price return exceeds gross TRI by up to 0.005% on some days |
| U06 | LOW | UNRESOLVED | Net TRI gains on gross TRI on 41 days (0.002-0.006%) |
| U07 | LOW | ACCEPTED_WITH_EVIDENCE | 11 net/gross jumps on bonus ex-dates: explained, not numerically reconciled |
| U08 | MEDIUM | UNRESOLVED | Gross and net independence unknown; net is a non-resident institutional measure |
| U09 | MEDIUM | UNRESOLVED | Revision behaviour of the endpoints untested |
| U10 | MEDIUM | UNRESOLVED | Only the Sep 2026 methodology document is held |
| U11 | LOW | UNRESOLVED | Factsheet CAGR convention unidentified; Nifty 50 gross since-inception not reproducible |
| U16 | LOW | UNRESOLVED | Large daily moves seen by one series only |

Full machine-readable detail: `benchmark_alignment_report.json`, `session_reconciliation_report.json`, `benchmark_unresolved_findings.json`.

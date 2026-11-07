# TRI endpoint investigation: Nifty 200 (2026-11-07)

Status: **investigation only - nothing ingested, no benchmark gate enabled.** Scope: Nifty 200 first.
Samples are in the session scratch area; one small real response is kept as a test fixture
(`tests/data/tri/nifty200_tri_2021-10-25_2021-11-02.json`).

## Request contract (read from the site's own scripts, then exercised)

* Form: niftyindices.com `/reports/historical-data`, "Total Returns Index" panel (report-type dropdown offers
  *Total Returns Index* and *Net Total Return Index*).
* `POST https://www.niftyindices.com/BackPage/getTotalReturnIndexString`
  `Content-Type: application/json; charset=utf-8`
  body: `{"cinfo": "{'name':'NIFTY 200','startDate':'31-Oct-2025','endDate':'30-Oct-2026','indexName':'Nifty 200'}"}`
  (`cinfo` is a STRING holding single-quoted pseudo-JSON; dates `dd-Mon-yyyy`; `name` = `Trading_Index_Name`
  upper-cased from `liveindexsa.niftyindices.com/assets/json/IndexMapping.json` - "Nifty 200" and "Nifty 50"
  are both present there).
* Cookies/headers: **not required** (a bare request with only User-Agent and Content-Type returned identical data).
* Response: HTTP 200, `Content-Type: text/html` but the body is a JSON array, newest first, one object per day:
  `{"RequestNumber":"TRI6392...","Index Name":"Nifty 200","Date":"30 Oct 2026","TotalReturnsIndex":"17750.88","NTR_Value":"-"}`
  Date format `dd Mon yyyy` (no time, no zone: a calendar date); value is a STRING with 2 decimals.
* **Range limit:** the page refuses more than 365 days (a client-side check added 2025-08-28). The server does
  NOT enforce it (a 2-year request returned 496 rows and no truncation). Decision: fetch in windows of at most
  365 days anyway, i.e. comply with the limit the site states, do not exploit its absence.
* No pagination. No truncation observed.

## What series is it?

Identified by evidence, not by the label. Official factsheet (30 Oct 2026) vs the endpoint:

| Measure | Base date | Endpoint | Factsheet Total Return | Factsheet Price Return |
|---|---|---:|---:|---:|
| QTD | 2026-09-30 | +0.15% | 0.15% | 0.11% |
| YTD | 2025-12-31 | -8.49% | -8.49% | -9.29% |
| 1 year | 2025-10-31 | -7.35% | -7.35% | -8.20% |
| 5 years (CAGR) | 2021-10-29 | 8.26% | 8.26% | 7.14% |
| Since inception (CAGR) | 2004-01-01 = 1000 | 13.43% | 13.42% | 11.95% |

It matches the **Total Return** column and not the price column, to the basis point (the since-inception 0.01
difference is day-count rounding). So `TotalReturnsIndex` is the **Nifty 200 Total Returns Index**.
Gross vs net: the methodology document defines the TRI as dividends **reinvested after the close on the
ex-date**, with special dividends (>= 2% of price) excluded from the TRI; that is the gross series. The
**Net TRI is NOT available for Nifty 200**: `NTR_Value` is "-" in every row (the site shows a net column only
for Nifty 50, Nifty Midcap 50 and Nifty 500 since 2025-12-18; not yet tested here).

## Coverage and quality of what was sampled

* History exists from **2004-01-01 at 1000.00** (the index base) to 2026-10-30 (checked 2004 and 2021 windows
  and the last two years).
* Last year (247 rows): no duplicate dates, no malformed or non-positive values, 2 decimals throughout, no gap
  longer than 4 days, largest move 3.96% (2026-04-08), largest 2-year moves 3.9% (2025-05-12).
* Re-fetching the identical range gives identical data. Only `RequestNumber` changes per response, so
  hashes must be taken over the data WITHOUT it.
* Against the exchange's bhavcopy trading days for the same year: every bhavcopy day has a TRI value; the TRI
  has ONE extra date, **Sunday 2026-02-01** (Union Budget special session, -2.0% vs Friday). The index is
  computed on every day the capital market segment is open. **This exposes a gap in OUR bars/calendar**: the
  bhavcopy pipeline never fetched that day because the calendar treats Sunday as closed (same risk for Budget
  Saturdays and Diwali muhurat sessions).
* Quirk: the `Index Name` column mixes "NIFTY 200" and "Nifty 200" within one response; never key on it.
* Not yet verified: revisions of past history across time (only same-day repeat tested), the full
  2004-2026 range, and the daily values against a second source beyond the factsheet returns above.

## Plan (unchanged by these findings)

1. Capture Nifty 200 TRI for 2004-01-01..today in <=365-day windows (about 23 requests, 6 s apart), each
   response stored UNTOUCHED in the lake with url, request body, retrieval time, status and sha256; stop on
   any refusal.
2. Parse to observations (one per date); reject duplicates, malformed or non-positive values; do not
   interpolate missing sessions; compare dates with the bhavcopy sessions and list the differences.
3. Register the benchmark (`data/benchmark.py`): index NIFTY 200, provider NSE Indices, return type
   TOTAL_RETURN, methodology = Nifty Indices Methodology Document, Sep 2026 (20260821) - historical
   methodology versions are NOT available; record that. Ingest immutably; pin `dataset_hash`.
4. Re-run the factsheet reconciliation on the stored data; only then enable it for the benchmark gates.
5. Then Nifty 50 (check its NTR_Value), then the Nifty 200 price index as a diagnostic only.

---

# Capture, validation and ingestion: Nifty 200 Gross TRI (2026-11-07)

Series: `index_id NIFTY_200`, `series_type GROSS_TRI`, `frequency DAILY`, `source NSE_INDICES`, start
2004-01-01 (base 1000.00), last observation 2026-11-06. Benchmark id 1 in the dev database. **The benchmark
gate is NOT enabled.**

## What was captured and stored (each kept separate)

| Item | Where | Identity |
|---|---|---|
| Raw endpoint responses | lake `tri_nifty200`, 23 untouched files (non-overlapping windows of <= 365 days) | sha256 per file; request body, status, rows, normalized hash per request in `capture_log.jsonl` |
| Parsed observations | `benchmark_observation` (immutable trigger), 5,673 rows | `dataset_hash 8cf2b57a...`; normalized capture hash `8a418b71...` (excludes RequestNumber, name casing, ordering) |
| Validation report | `benchmark_validation` | stored with the dataset hash it was made on; `validated()` is false if the series later changes |
| Factsheet evidence | lake `factsheet_nifty200` (30 Oct 2026 edition) + `config/factsheet_checks/nifty200_2026-10-30.json` | sha256 `bc0bc80d...` |
| Methodology | Nifty Indices Methodology Document, Sep 2026 (20260821) | only this version is held |

Capture protocol followed: sequential, 6 s apart, windows consecutive (no overlap, so no conflicting
overlap to resolve), stop-on-refusal rules, no refusals occurred.

## Validation results

| Check | Result |
|---|---|
| First observation / base level | 2004-01-01 / 1000.00 |
| Duplicate dates, conflicting values, rows outside their window, non-positive or malformed values | 0 |
| Index-name variants ("NIFTY 200" / "Nifty 200") | tolerated; identity is the benchmark id, not the name |
| Gaps over 5 days | one: 2014-10-01 .. 2014-10-07 (consistent with the early-October 2014 holidays; not interpolated) |
| Largest daily moves | 16.75% (2009-05-18), 12.78% (2020-03-23), 12.21% (2004-05-17), 11.27% (2008-10-24), 10.32% (2008-01-21): all coincide with major market events (election results, the 2008 crash, March 2020); investigated, not rejected, and not checked against an independent daily series |
| Trading-day comparison with our bhavcopy days (2019-10 .. 2026-11) | every bhavcopy day has a benchmark value; benchmark values without a bhavcopy: 2022-08-08 only (quarantined spreadsheet) |
| Factsheet returns on the STORED data | QTD +0.0005 pp, YTD -0.0027 pp, 1 year -0.0001 pp, 5y CAGR +0.0003 pp, since inception +0.0086 pp: all within the stated tolerances |

**Since-inception CAGR (13.43% computed vs 13.42% published):** determined to be a day-count convention
difference, not a data difference. The cumulative returns (no convention involved) agree to <= 0.003 pp.
Actual/365 reproduces the published inception figure (13.4188 -> 13.42) but not the 5-year figure
(8.2544 -> 8.25 vs 8.26); actual/365.25 reproduces the 5-year figure but not inception. No single simple
convention reproduces both, so the factsheet's convention is unidentified. Kept as a recorded difference
(tolerance 0.02 pp), not forced to equality.

## Special trading sessions (a required part of this milestone)

* The series has values on **27 weekend dates** (2004-2026), so the calendar's "weekends are closed"
  assumption was wrong for the exchange. The calendar now has explicit session types
  (REGULAR / SPECIAL / MUHURAT / CLOSED, `SessionCalendar.session_type`) driven by an evidence file
  `config/exchange_sessions.json` (28 sessions: the 27 weekend dates + Thursday 2021-11-04), each entry
  stating its evidence and what is unknown: **kind** (Budget day, Muhurat or an exchange drill) is
  UNCONFIRMED and **hours** are UNKNOWN (regular hours assumed for bar visibility).
* Official bhavcopy exists for every one of the 9 weekend sessions inside our bar history (2019-10-27,
  2020-02-01, 2020-11-14, 2023-11-12, 2024-01-20, 2024-03-02, 2024-05-18, 2025-02-01, 2026-02-01) and is
  now loaded through the normal pipeline. The Diwali 2021 Muhurat session (2021-11-04) was recovered from the
  file NSE served under 2021-11-05 (its rows are dated 2021-11-04; it had been quarantined because the row date
  differed from the requested date); the true source URL is recorded.
* Reconciliation of the loaded bars with the benchmark on those 10 sessions: TRI move vs median Nifty 200
  stock move - 2019-10-27 +0.44/+0.47, 2020-02-01 -2.64/-2.59, 2020-11-14 +0.48/+0.54, 2021-11-04
  +0.53/+0.63, 2023-11-12 +0.53/+0.44, 2024-01-20 -0.05/-0.42, 2024-03-02 +0.31/+0.43, 2024-05-18
  +0.31/+0.33, 2025-02-01 -0.06/-0.34, 2026-02-01 -2.04/-2.17 (%): same sign on all ten.
* **Limitation:** weekend sessions are complete for the whole TRI history, but weekday special sessions
  before 2019-10 (e.g. Muhurat on a holiday weekday) cannot be identified without historical holiday
  lists; the 17 weekend dates before 2019-10 are listed but have no bars (we hold none).
* Rule kept: no bar or return is manufactured for a date without trading data.

## Unresolved (stored in `benchmark_validation.unresolved`, not marked verified)

1. Historical revision behaviour (only a same-day repeat was compared).
2. Independent reconciliation: the factsheet is the same publisher's document.
3. Historical methodology versions (only Sep 2026 held).
4. Special-session kinds and hours; weekday special sessions before 2019-10.
5. 2022-08-08 bhavcopy (quarantined).
6. Factsheet CAGR convention.
7. No net TRI exists for Nifty 200.

## Next

Nifty 50 gross TRI (check its `NTR_Value` net series, keep it separate), then the Nifty 200 price index as a
diagnostic only. The benchmark gate stays disabled until the owner approves it and a later re-fetch has been
compared for revisions.

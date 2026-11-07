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

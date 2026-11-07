# Trading costs (`src/algo/backtest/costs/`, `config/cost_schedules/`)

Goal: a trade-level cost engine that can explain every rupee deducted from a simulated trade, with
the exact schedule version and source behind it. **No rate is written in code.** Rates are DATA in
`config/cost_schedules/*.json`, each component citing a source: url + sha256 of the stored document
+ a literal quote (checked to be present in the document when the file is built).

## Evidence pipeline
1. `scripts/capture_cost_sources.py` stores the official documents untouched in the versioned raw
   lake (`raw/costs/<name>/...`, sha256 in the manifest).
2. `scripts/build_cost_schedules.py` writes the JSON schedules from them and **fails if any quote is
   not literally present** in its document. To change a rate, change the cited document and re-run.
3. A PERSON verifies each quote against its document, then sets `status: verified`, `verified_by`,
   `verified_at`. Until then every schedule is `extracted_unverified` (or `assumed_backfill`).

## Schedule status and where it may be used
| status | meaning | usable |
|---|---|---|
| verified | checked by a named person against the cited documents | strict and research; may support promotion |
| extracted_unverified | read from the documents, not yet verified | research only |
| assumed_backfill | a CURRENT rate extended into a period it is not evidenced for | research only, explicit opt-in, flagged on the run |

A run's `ScheduleBook` is built with the statuses it allows. No schedule in force on a trade date =>
`NoScheduleForDate`: the run stops rather than guessing.

## What is evidenced (fetched 2026-11-07) and what is not
| component | rate | evidence | dated? |
|---|---|---|---|
| STT delivery | 0.1% buy and sell | NSE circulars 2016, 2023, 2024, 2026 (all "No Change") | continuous across the window |
| STT intraday | 0.025% sell | same circulars | continuous |
| Stamp duty | 0.015% delivery / 0.003% intraday, buyer | NSE page | from 2020-07-01 |
| NSE transaction | 0.00307% (306.99 + 0.01 IPFT per crore) | NSE/FA/73061 + Zerodha | structure from 2026-03-01; total was already 307 |
| SEBI turnover fee | 0.0001% (Rs 10/crore) | NSE, Zerodha pages | undated |
| GST | 18% of (brokerage + SEBI + transaction) | Zerodha, NSE pages | undated |
| Brokerage | delivery Rs 0; intraday 0.03% capped Rs 20/order | Zerodha page | observed 2026-11-07 only |
| DP charge | Rs 15.34 per scrip on each delivery SELL (GST included) | Zerodha page | undated |
| Contract-note minimum | Rs 0.01 per delivery contract note | Zerodha page | undated |

Why the assumed backfill is only approximate: before Oct 2024 the exchange's transaction charge was a
member tariff that depended on each member's monthly turnover (about Rs 3.00-3.45 per lakh, circular
NSE/FA/56129), so the rate a retail client saw back then is not derivable from the circulars. Zerodha's
page has no history for brokerage, DP charges, GST or the SEBI fee. Historical broker schedules or
contract notes are needed to verify those periods.

## How a charge is computed (`calculator.py`)
Per executed order, per component, rounded half-up to the paisa (unless `rounding: NONE`); GST is the
last line, on the sum of components flagged `taxable_for_gst`. Components that already include GST
(DP charge) are flagged `gst_inclusive`. Every `ChargeLine` carries its basis value, formula text,
rounding and source key, and the `Charges` carries the schedule id / version / status.
Rounding is NOT documented by the broker; a contract note may round on day totals, so
`reconcile.py` allows up to Rs 0.01 per order per component and reports those separately from real
discrepancies. The tests pin hand-computed orders (e.g. delivery buy 100 @ 1000 = 118.74).

## Slippage (`slippage.py`) is not a charge
An execution-model estimate: base bps + bps per 1% participation + a share of the recent average
daily range + an illiquidity surcharge, capped. Inputs come only from sessions BEFORE the execution
bar plus the order's own share of that bar's volume. A run with zero slippage cannot support
promotion. Daily OHLCV says nothing about the depth available at the open; stronger execution
simulation needs intraday or quote data.

## In the backtest
The engine sizes a buy by bisection so the all-in cost (shares at the slipped fill + all charges)
fits the cash. Each trade stores its itemised charges (`backtest_trade.charges`), the ledger holds a
fee entry and a cash entry per charge type, and `backtest_ledger_fees` totals them. The run record
lists the schedules used; unverified/assumed schedules, a placeholder model and zero slippage each
block promotion.

## Not built yet
* Verification of the schedules by a person; historical broker schedules / contract notes.
* Reconciliation against a REAL contract note and against Zerodha's brokerage calculator (the tool
  `reconcile_note` exists and is tested on hand-built notes).
* Intraday product in the engine (the schedules exist; the engine is daily and holds overnight).
* Equity futures (STT 0.01% -> 0.0125% -> 0.02% -> 0.05% history is in the fetched circulars).

# Cost schedule verification worksheet (current schedules, valid from 2026-03-01)

Only a named person can set a schedule to `verified` (docs/costs.md). For each line: open the stored document at the path given (its
SHA-256 is recorded), find the quote, and confirm that the RATE in the schedule is what the document says for a retail Zerodha client.
`build_cost_schedules.py` already proved every quote is literally present; it cannot prove the rate was read correctly.

## nse-cash-delivery-zerodha-2026-03-01 (DELIVERY), 2026-03-01 onwards, status `extracted_unverified`

| # | component | side | rate / parameters | source document (stored copy) | quote to find | checked |
|---|---|---|---|---|---|---|
| 1 | BROKERAGE | BOTH | rate_pct=0; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "All equity delivery investments (NSE, BSE), are absolutely free — ₹ 0 brokerage." | [ ] |
| 2 | STT | BOTH | rate_pct=0.1; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "0.1% on buy & sell" | [ ] |
| 3 | EXCHANGE_TRANSACTION | BOTH | rate_pct=0.00307; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "NSE: 0.00307%" | [ ] |
| 4 | SEBI_TURNOVER | BOTH | rate_pct=0.0001; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "Charged at ₹10 per crore + GST by Securities and Exchange Board of India" | [ ] |
| 5 | STAMP_DUTY | BUY | rate_pct=0.015; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "0.015% or ₹1500 / crore on buy side" | [ ] |
| 6 | DP_CHARGE | SELL | amount=15.34; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "₹15.34 per scrip (₹3.5 CDSL fee + ₹9.5 Zerodha fee + ₹2.34 GST) is charged on the trading account ledger when stocks are sold, irrespective of quantity." | [ ] |
| 7 | GST | BOTH | rate_pct=18; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "18% of ( brokerage + SEBI charges + transaction charges)" | [ ] |

Contract-note minimum brokerage: 0.01. Notes: Rates read from the cited documents on 2026-11-07. Valid from 2026-03-01, the one effective date the documents state for the current NSE charge structure. Zerodha's page carries no effective dates, so BROKERAGE / DP_CHARGE / GST / SEBI are evidenced as 'published on retrieval date' only. Needs a person to verify each quote against its document. IPFT is inside the 0.00307%.

## nse-cash-intraday-zerodha-2026-03-01 (INTRADAY), 2026-03-01 onwards, status `extracted_unverified`

| # | component | side | rate / parameters | source document (stored copy) | quote to find | checked |
|---|---|---|---|---|---|---|
| 1 | BROKERAGE | BOTH | rate_pct=0.03, maximum=20; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "0.03% or Rs. 20/executed order whichever is lower" | [ ] |
| 2 | STT | SELL | rate_pct=0.025; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "0.025% on the sell side" | [ ] |
| 3 | EXCHANGE_TRANSACTION | BOTH | rate_pct=0.00307; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "NSE: 0.00307%" | [ ] |
| 4 | SEBI_TURNOVER | BOTH | rate_pct=0.0001; GST-taxable=True, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "Charged at ₹10 per crore + GST by Securities and Exchange Board of India" | [ ] |
| 5 | STAMP_DUTY | BUY | rate_pct=0.003; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "0.003% or ₹300 / crore on buy side" | [ ] |
| 6 | GST | BOTH | rate_pct=18; GST-taxable=False, rounding=HALF_UP_2DP | https://zerodha.com/charges (`data/lake/raw/costs/zerodha_charges/dt=2026-11-07/v0001.bin`, sha256 `7ca369d276e5798a...`) | "18% of ( brokerage + SEBI charges + transaction charges)" | [ ] |

Contract-note minimum brokerage: None. Notes: Rates read from the cited documents on 2026-11-07. Valid from 2026-03-01, the one effective date the documents state for the current NSE charge structure. Zerodha's page carries no effective dates, so BROKERAGE / DP_CHARGE / GST / SEBI are evidenced as 'published on retrieval date' only. Needs a person to verify each quote against its document. IPFT is inside the 0.00307%.

## What contract notes are needed (to verify the periods the schedules cannot)

The research window starts 2020-10-01. Between 2020-07-01 and 2026-02-28 only an `assumed_backfill` exists (today's rates extended back).
Brokerage, DP charge, GST base and the SEBI fee have no dated public history, and the exchange transaction charge a client paid before
October 2024 depended on Zerodha's member slab. Contract notes are the evidence for those periods.

| Period | Why | Needed |
|---|---|---|
| 2020-10 .. 2024-09 | slab-era exchange transaction charge; brokerage/DP history | one delivery BUY and one delivery SELL contract note per calendar year 2020 (Q4), 2021, 2022, 2023, 2024 (before October) |
| 2024-10 .. 2026-02 | SEBI 'true to label' exchange charge (from 2024-10-01) | one delivery BUY and one delivery SELL contract note |
| 2026-03 .. now | the current schedule (structure from 2026-03-01) | one delivery BUY and one delivery SELL contract note |
| any period with a sale | the DP charge is billed separately from the contract note | the Console ledger or DP charges bill for one delivery sell per period |

Format: the PDF contract note as emailed by Zerodha (password-protected with the PAN), or the Console tax P&L / tradewise charges export.
Place them under `data/evidence/contract_notes/` (gitignored). They contain personal data; nothing from them is committed except the
component totals and a SHA-256 of each file. With them: `reconcile_note` compares every component per trading day, and a schedule per
period can be built from evidence instead of assumed.

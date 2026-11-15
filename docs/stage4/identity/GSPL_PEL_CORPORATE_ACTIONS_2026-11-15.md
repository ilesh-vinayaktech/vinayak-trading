# GSPL and PEL corporate actions: what is established, what is missing (2026-11-15)

Purpose: U2 needs bars for GSPL and PEL, and the bars were held until their corporate actions are loaded and validated. **Nothing was loaded, applied or changed.**

## Established, with primary or near-primary evidence
| Stock | Event | Evidence | Price effect on the stock's own history |
|---|---|---|---|
| GSPL | Amalgamation into Gujarat Gas (GUJENERGY), effective about 2026-05-01, **record date 2026-05-12**, last session 2026-05-11. Ratio **10 GGL shares (INR 2) for every 13 GSPL shares (INR 10)**. | The company's own filing to NSE (Reg 30, "Record Date and noting of Order", 2026-04-29), saved: `data/evidence/identity/gspl_nse_filing_record_date_2026-04-29.pdf`, sha256 `946f56e683d1dd9ca69e082f33b93ad8501e5353b50f61f943b10ba56bd8f20d`. This **upgrades the ratio from "search results only" to a primary document**. | None: the shares are cancelled and the stock stops trading. GSPL's later large moves in the bars (2024-04-22 x0.80, 2024-08-26 x1.11) have no recorded corporate action behind them (NSE did not adjust the previous close). |
| PEL | **Demerger of the pharma business**, ex-date **2022-08-30**, record date 2022-09-01, **4 Piramal Pharma shares for 1 PEL share**. PEL's F&O contracts were settled out on 2022-08-29 and re-listed (lot 275) from 2022-08-30. | Zerodha forum copy of NSE circular FAOP53436 (circular itself not retrieved); press. Piramal's own Section 49(2C) report allocates **6.58%** of cost to the pharma shares (a tax figure, saved: `pel_ppl_demerger_cost_report_s492c_2022-08.pdf`, sha256 `5637e0f35f5d5ec1321cd4dcf41450c2a114e61ad90583aef5e4600810094adf`). | The close falls 1,926.50 to 1,063.55 (x0.5521). **No exchange base price exists in our files** (no special session in 2022; the ex-date open 1,055.05 is an ordinary open, PREV_CLOSE is the raw cum close). |
| PEL | Merger into Piramal Finance (PIRAMALFIN), 1:1, NCLT approval 2025-09-10, effective 2025-09-16, record date 2025-09-23, relisted as PIRAMALFIN 2025-11-07. | Press and the NSE listing circular (as reported). | None on PEL's history: it ends. |

## Missing
1. **The exchange adjusted base price for the PEL demerger on 2022-08-30.** The owner's methodology (market-value adjustment from the exchange base price) cannot be applied without it. This is the same gap as the four held demergers (NMDC, GMRAIRPORT, MOTHERSON, ABB). Press hints (the stock "surged 9%" on the ex-date, "down 44%") imply NSE displayed an adjusted base, but the figure is not in any retrievable source; a stored-price gap estimate would be PROVISIONAL and cannot reach VERIFIED.
2. **A complete list of NSE corporate actions for GSPL and PEL** (dividends are irrelevant to price adjustment, but splits, bonuses and rights are not). The lake holds action files for 2,634 symbols and none for these two, because `ingest_symbol` skips any symbol whose alias has ended. Without the feed I cannot show that no other price-affecting action exists in 2019-10 to 2026; a scan of the stored bhavcopy files is too noisy to prove it (sessions after missing files look like adjustments).

## What I did not do, and why
I tried to ask NSE's corporate-actions JSON for the two symbols directly. The environment refused it (scripted, browser-style access to NSE's website API), and I did not look for a way around that. The sanctioned route is the project's own job (`scripts/backfill_nse.py`, stage `actions`), which does exactly this fetch for the other 2,634 symbols.

## Proposed next steps (need the owner)
1. **Load the two symbols' action history through the project's own ingest.** I can prepare the change (let `ingest_symbol` include a symbol whose alias has ended, add `--symbols`, tests first) and you run it, or you authorise me to run it.
2. **PEL demerger**: treat it as the fifth gap-era demergers needing the NSE adjusted base price; until then record it as a PROVISIONAL estimate (research mode only, strict mode refuses), or hold PEL's bars from before 2022-08-30 out of strict studies.
3. **Bars**: load GSPL (1,639 rows, 2019-10-01..2026-05-11) and PEL (1,485 rows, ..2025-09-22) only after step 1; strict mode would still refuse PEL across 2022-08-30 until the base price is found. That would clear U2's "member without a bar" for GSPL fully, and for PEL in research mode.
4. GSPL relationship: with the ratio now in a company filing, the relationship `AMALGAMATED_INTO GUJENERGY 10:13` can be proposed for verification (it is PROVISIONAL today).

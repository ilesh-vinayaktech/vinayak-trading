# GSPL and PEL corporate actions: what is established, what is missing (2026-11-15)

**CORRECTION (same day, after the owner's review):** the first version said there was no special session for PEL in 2022 and that no exchange base price existed in our files. **That was wrong.** NSE circular NSE/CMTR/53437 (93/2022, 25 Aug 2022) ran a one-hour pre-open call auction for PEL on 30 Aug 2022 and states "Post price discovery, base price shall be the discovered price". See the section "PEL demerger base price" below; the "Missing" list is updated.

Purpose: U2 needs bars for GSPL and PEL, and the bars were held until their corporate actions are loaded and validated. **Nothing was loaded, applied or changed.**

## Established, with primary or near-primary evidence
| Stock | Event | Evidence | Price effect on the stock's own history |
|---|---|---|---|
| GSPL | Amalgamation into Gujarat Gas (GUJENERGY), effective about 2026-05-01, **record date 2026-05-12**, last session 2026-05-11. Ratio **10 GGL shares (INR 2) for every 13 GSPL shares (INR 10)**. | The company's own filing to NSE (Reg 30, "Record Date and noting of Order", 2026-04-29), saved: `data/evidence/identity/gspl_nse_filing_record_date_2026-04-29.pdf`, sha256 `946f56e683d1dd9ca69e082f33b93ad8501e5353b50f61f943b10ba56bd8f20d`. This **upgrades the ratio from "search results only" to a primary document**. | None: the shares are cancelled and the stock stops trading. GSPL's later large moves in the bars (2024-04-22 x0.80, 2024-08-26 x1.11) have no recorded corporate action behind them (NSE did not adjust the previous close). |
| PEL | **Demerger of the pharma business**, ex-date **2022-08-30**, record date 2022-09-01, **4 Piramal Pharma shares for 1 PEL share**. PEL's F&O contracts were settled out on 2022-08-29 and re-listed (lot 275) from 2022-08-30. | Zerodha forum copy of NSE circular FAOP53436 (circular itself not retrieved), the company's record-date filing and NSE/CMTR/53437 (preserved below). Piramal's own Section 49(2C) report allocates **6.58%** of cost to the pharma shares (a tax figure, saved: `pel_ppl_demerger_cost_report_s492c_2022-08.pdf`, sha256 `5637e0f35f5d5ec1321cd4dcf41450c2a114e61ad90583aef5e4600810094adf`). | The close falls 1,926.50 to 1,063.55 (x0.5521). The exchange base price is the pre-open call-auction price, 1,055.05 (see the section below); PREV_CLOSE in the file is the raw cum close. |
| PEL | Merger into Piramal Finance (PIRAMALFIN), 1:1, NCLT approval 2025-09-10, effective 2025-09-16, record date 2025-09-23, relisted as PIRAMALFIN 2025-11-07. | Press and the NSE listing circular (as reported). | None on PEL's history: it ends. |

## PEL demerger base price (corrected)
- **Rule (primary):** NSE/CMTR/53437, 25 Aug 2022, saved `data/evidence/identity/nse_CMTR53437_pel_preopen_call_auction_2022-08-25.pdf` (sha256 `f429671ffa307bf72058649dc41556b9a84e55b4b67869a10bd371b2a7421f6e`): a Pre-Open 2 call auction for PEL on 2022-08-30, 9:00 to 10:00, "Post price discovery, base price shall be the discovered price".
- **Price (primary file):** the stored NSE bhavcopy for 2022-08-30 (`data/lake/raw/nse/bhav/dt=2022-08-30/v0001.bin`, sha256 `209b1e2e0335813c897ba11908774de05ea69d3f892f5357b2d7bded463cb05f`), PEL EQ: PREV_CLOSE 1926.50, **OPEN_PRICE 1055.05**, LOW 1050.00, CLOSE 1063.55. The previous session's file (2022-08-29) has CLOSE 1926.50.
- **The reported Rs 1,050 is not this price.** Business Standard's "opened at Rs 1,050" is the **BSE** price, in the same sentence as BSE's previous close of Rs 1,935 (NSE's is 1,926.50). NSE's own open is 1,055.05; Rs 1,050.00 is the day's NSE low. So the rule "if the bhavcopy shows Rs 1,050" is not met, and the difference is explained by the exchange, not by an error. Nothing independent of NSE's own file confirms 1,055.05.
- **Factor (market-value adjustment, as approved):** 1055.05 / 1926.50 = **0.5476511808980015572281339216**. It is close to the earlier price-gap estimate (0.5521), and nowhere near the 6.58% tax allocation, which is not used.
- **Proposed treatment:** method `exchange_adjusted_price`, base_price 1055.05, prev_close 1926.50, with provenance **EXCHANGE_DERIVED_BHAVCOPY_PREOPEN**: a primary rule plus the exchange's own file, with the BSE figure explained and no independent corroboration of the number. It is NOT proposed as VERIFIED; the owner decides. PEL is therefore **not** the fifth held demerger. **Nothing was loaded or modified.**

## Other primary documents now preserved (`data/evidence/identity/`)
| Document | What it establishes | sha256 (first 16) |
|---|---|---|
| PEL record-date filing, 2022-08-18 | Record date 2022-09-01; 4 PPL shares (Rs 10) for 1 PEL share (Rs 2) | `b6ff4dd9a28a124d` |
| NSE/CML/74078, 2026-05-06 | GSPL suspended from trading w.e.f. 2026-05-12 (last session 2026-05-11), "Scheme of Amalgamation": GSPL's own history ends there; no prices are manufactured after it | `470b11622b158bbc` |
| PEL Reg 30 filing, effectiveness | The scheme of merger became effective 2025-09-16; PEL merged into Piramal Finance and dissolved without winding up | `15debfc3cf283bd6` |
| GSPL filing to NSE, 2026-04-29 | 10:13 ratio, record date 2026-05-12 | `946f56e683d1dd9c` |

## Still missing
**A complete list of NSE corporate actions for GSPL and PEL.** The sources above verify the named events; they do not show that no other split, bonus, rights issue or similar action occurred in 2019-10 to 2026. The lake holds action files for 2,634 symbols and none for these two, because `ingest_symbol` skips any symbol whose alias has ended. A scan of the stored bhavcopy files cannot prove absence (sessions after a missing file look like adjustments), so absence is not inferred.

## What I did not do, and why
I tried to ask NSE's corporate-actions JSON for the two symbols directly. The environment refused it (scripted, browser-style access to NSE's website API), and I did not look for a way around that. The sanctioned route is the project's own job (`scripts/backfill_nse.py`, stage `actions`), which does exactly this fetch for the other 2,634 symbols.

## Proposed next steps (need the owner)
1. **Load the two symbols' action history through the project's own ingest.** I can prepare the change (let `ingest_symbol` include a symbol whose alias has ended, add `--symbols`, tests first) and you run it, or you authorise me to run it.
2. **PEL demerger**: record it from the exchange base price above (1055.05 / 1926.50) and decide its provenance label; it needs no gap estimate.
3. **Bars**: load GSPL (1,639 rows, 2019-10-01..2026-05-11) and PEL (1,485 rows, ..2025-09-22) only after step 1; strict mode would still refuse PEL across 2022-08-30 until the base price is found. That would clear U2's "member without a bar" for GSPL fully, and for PEL in research mode.
4. GSPL relationship: with the ratio now in a company filing, the relationship `AMALGAMATED_INTO GUJENERGY 10:13` can be proposed for verification (it is PROVISIONAL today).

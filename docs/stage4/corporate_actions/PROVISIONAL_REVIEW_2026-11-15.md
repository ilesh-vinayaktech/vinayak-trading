# The 20 PROVISIONAL corporate actions on Nifty 200 members: evidence and proposals (2026-11-15)

Strict mode refuses prices while any action is provisional (`reader.py`), so these 20 are what blocks readiness C1. 901 other non-dividend actions are already resolved with a reason.
Nothing here is applied: the database is unchanged. Numbers: `provisional_cross_check_2026-11-15.csv` (stored factor vs the factor Kite's adjusted candles imply).

## What the cross-check actually measures
Kite adjusts RIGHTS by the exchange price effect, so it corroborates a rights factor. For DEMERGERS Kite uses the TAX cost-allocation ratio, which is not the same quantity as the exchange's
market-value adjustment. Every demerger below shows it: ITC Kite 0.865 = ITC's 86.49:13.51 cost split; Jio 0.9532 = 95.32:4.68; TMPV 0.6885 = 68.85:31.15; Vedanta 0.5234 = 52.34%.
The stored demerger factors are the MARKET adjustment (the price discovered in NSE's special pre-open session over the previous close), which is what keeps a holder's value continuous. So for
demergers "not corroborated by Kite" is expected and is not evidence the stored factor is wrong. **Methodology decision needed from the owner: market adjustment (stored, recommended; it is what NSE
itself does for its indices, and what a trader's mark-to-market sees) or tax cost ratio.**

## A. Propose VERIFIED: independent evidence agrees (10)
| Action | Stored | Evidence |
|---|---|---|
| Rights: SHRIRAMFIN 2020-07-09, LTF 2021-01-21, BHARTIARTL 2021-09-27, INDHOTEL 2021-11-11, SUZLON 2022-10-03, GRASIM 2024-01-10, TATACONSUM 2024-07-26, UPL 2024-11-26, ADANIENT 2025-11-17 | from issue terms | Kite's independent adjustment agrees within 0.15% on all nine (ratio 0.9999 to 1.0014) |
| HINDUNILVR demerger 2025-12-05 | 0.98367 (special-session price 2,422.00 over 2,462.20) | Kite 0.9809 (0.3% apart, a market vs cost difference this small is plausible for a 1.6% adjustment) |

## B. Propose VERIFIED as exchange-derived, press-corroborated (5): the original NSE circulars are still not in hand
The stored factor times the previous close reproduces the special-session price the press reports, to the paisa:
| Demerger | Previous close (NSE bars) | Stored factor gives | Press-reported special-session price |
|---|---|---|---|
| RELIANCE / Jio Financial, 2023-07-20 | 2,841.85 | 2,580.00 | Rs 2,580 (JFSL valued Rs 261.85) |
| ITC / ITC Hotels, 2025-01-06 | 481.60 | 455.60 | "ITC discovered price at Rs 455.6, down Rs 26" (moneycontrol via TradingView) |
| SIEMENS / Siemens Energy India, 2025-04-07 | 4,928.15 | 2,450.00 | opened Rs 2,450 against 4,928.15 (Angel One) |
| TATA MOTORS (TMPV), 2025-10-14 | 660.75 | 400.00 | discovered about Rs 400, down 260.75 (Upstox, Business Today) |
| VEDL, 2026-04-30 | 773.60 | 289.50 | settled Rs 289.50 on NSE, fell 62% (Angel One, Outlook Business) |
Caveat: these are press reports of NSE's price, not the circular. If the owner wants the circular, it is the one gap left; the stored note already says so.

## C. NOT resolved: need NSE's adjusted base price or a correction (5)
| Action | Stored | Finding |
|---|---|---|
| **NMDC 2022-10-27** | 0.7914 (gap; implies 103.47) | **Likely wrong by about 10%.** Press: NMDC "surged 14.46% to Rs 107.25" on the ex-date, which puts the exchange's adjusted base near Rs 93.7 (factor about 0.717). 1:1 NMDC Steel. Needs the NSE base price to fix; the stored "gap" mixes the market move into the factor. |
| GMRAIRPORT 2022-01-11 | 0.9277 (gap) | Company's own cost split is 92.71:7.29 = 0.9271, 0.06% apart; but that is the cost ratio, not the market adjustment. Needs the exchange base price. |
| MOTHERSON 2022-01-14 | 0.7909 (gap) | Press: fell up to 22% from the prior NSE close (consistent with the gap), also "fell 9%" (against an adjusted base we do not have). 1:1 wiring harness. Needs the exchange base price. |
| ABB 2019-12-20 | 0.8544 (gap) | 1 ABB Power Products share per 5 ABB India; ex-date about 20 Dec, record 23 Dec 2019. Needs the exchange base price. |
| RELIANCE rights 2020-05-13 | 0.9906 (terms) | Partly paid (Rs 314.25 of Rs 1,257 on application). Kite does not adjust it (1.0000), so no independent check; the effect is at most 1%. Needs the NSE circular for the ex-date. |

The four gap-era demergers (ABB, GMR, MOTHERSON, NMDC) predate NSE's special pre-open session, so no single price like those in B exists; the exchange's adjusted base price is the missing evidence and the Business Standard pages that quote it block automated fetches.

## Proposed next step
1. Owner decides the demerger methodology (market adjustment recommended).
2. On approval: verify group A (10) and group B (5) in the owner's name, with this document as the evidence note.
3. Owner or I obtain the NSE base prices for group C (NSE circulars / F&O adjustment notices for 2019 to 2022); until then those 5 keep C1 failing. NMDC is corrected rather than verified.

## Update after the owner's evidence review (2026-11-15, same day)
- **Methodology approved: market-value adjustment** for demerger price factors. The tax cost-allocation ratio is separate tax metadata.
- **SUZLON**: the issuer's own Letter of Offer (filed with SEBI and the exchanges 2022-09-28) is now on file with its SHA-256 (`data/evidence/rights/suzlon_2022_letter_of_offer_sebi.pdf`): 5:21, record date 2022-10-04, issue price Rs 5.00. Its label `ISSUER_TERMS_KITE_CORROBORATED` is now accurate.
- **RELIANCE rights 2020-05-13 is resolved by primary exchange evidence**: NSE circular NSE/FAOP/44356 (46/2020, 2020-05-12). P = 1,479.25 (our bars' previous close), S = 1,257, 1:15, E = 13.890625, AF = 0.990610. The stored factor, recomputed from the circular's own inputs, is 0.9906096839614669596079094136. New provenance `EXCHANGE_CIRCULAR_VERIFIED`. This corrects an earlier statement in this pack that Kite not adjusting it left "no independent check": the circular is the check.
- **Still provisional (4)**: NMDC, GMRAIRPORT, MOTHERSON, ABB. For NMDC the press figure of Rs 93.70 is reported from BSE, not NSE, so it is a warning and not a correction. C1 stays failing; the reader's rule is unchanged.
- The 16 verifications are prepared, **not applied**.

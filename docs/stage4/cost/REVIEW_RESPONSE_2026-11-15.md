# Response to the cost-schedule review (2026-11-15)

Outcome: **agreed that none of the eight delivery schedules should be VERIFIED now.** Several findings are right and some of the reasons given are not; each was checked against the code and primary documents, not taken on trust.
Nothing in `config/cost_schedules/` was changed (a schedule change moves backtest costs, and it needs tests run).

## Finding by finding
| # | Finding | Verdict | Evidence |
|---|---|---|---|
| 1 | GST is not 18% of value | **Not a defect in the schedules or the engine; it was a bug in my review-pack generator** (fixed). | `calculator.py`: a `GST_BASE` component computes `rate x gst_base`, where gst_base is the sum of components flagged `taxable_for_gst` (brokerage, exchange transaction, and SEBI fee from 2022-07-18). The generator printed every `rate_pct` as "% of value". It now says "18% of the GST base" and shows an "In GST base" column. |
| 2, 3 | DP charge Rs 13 assumed throughout; Rs 13.50 earlier | **Valid.** | Zerodha's own pages describe Rs 13.50 (Rs 5.50 CDSL + Rs 8) plus 18% GST per stock per day; Rs 13 is documented only just before 1 Oct 2024. A CDSL cut of 50 paise is mentioned in a forum thread with no date. **The date Rs 13.50 became Rs 13 is not established**; it must not be invented. Effect: up to Rs 0.59 per sale per scrip. |
| 4 | 0.00345% cannot apply throughout 2016 to 2020 | **Valid, and I have the primary document.** | NSE/FA/46730 (2020-12-18), saved in `data/evidence/cost/nse_FA46730_2020-12-18.pdf`, sha256 `a9ff85ab4deec82e02bb1e3fc213a2bbc02a72e9edb7b36cdf1568aeb792febf`: Cash Market, first slab, existing Rs 3.25 per lakh each side, revised Rs 3.45, and it states "applicable with effect from January 01, 2021". So 0.00345% is evidenced only from 2021-01-01. Caveat: that is NSE's **member** tariff, not what Zerodha charges a client; the client rate before 2021 (0.00325% by pass-through) is an assumption until Zerodha's page for that date is found. A temporary concessional scheme for EQ-series stocks outside Nifty 50 / Next 50 also ran 2020-08-01 onwards (FA45147: Rs 2.75, Rs 1.75 on incremental turnover; extended by FA47844 and FA49796, revised from 2022-04-01 by FA51855); whether Zerodha passed it to clients is unknown. |
| 5 | Pre-July-2020 stamp duty | **Valid.** | State-specific before 2020-07-01; the uniform 0.015% is an assumption. Outside the research window (starts 2020-10-01). To be labelled ASSUMED. |
| 6 | SEBI fee GST from 2022-07-18 | **Already modelled; evidence is the weak part.** | `taxable_for_gst` for SEBI_TURNOVER flips from false to true exactly at the 2022-07-18 schedule. But the source is the owner's cost note, not a stored document: the SEBI circular of 2022-07-18 should be fetched and saved. Not done yet. |
| 7 | Service tax before 2017-07-01 | **Valid.** | Not modelled; acknowledged in the 2016 schedule. Outside the research window. |
| 8 | DP charge per scrip per debit day | **Holds in the backtest; not checked for paper trading.** | `engine.py`: the order loop places at most one fill per instrument and side per day, so one DP charge per scrip per sale day. `paper/orders.py` also calls `compute_charges` per fill and may charge more than once for several fills; needs a test. |

## What this does to the window (2020-10-01 onwards)
- **Exchange fee, 2020-10-01 to 2020-12-31**: the schedule uses 0.00345%; the evidence supports 0.00325% (assumed client rate) until 2021-01-01. Three months, 0.2 bp of turnover per side.
- **DP charge, whole window**: Rs 15.34 (Rs 13 + GST) is documented from before 2024-10-01 only; earlier periods may be Rs 15.93 (Rs 13.50 + GST).
- **SEBI fee**: GST treatment before 2022-07-18 rests on the owner's note.
- 2024-04-01 onwards is the best evidenced; even there the sources are Zerodha pages read on a retrieval date, not archived.

## Proposed corrections (not applied; they change backtest costs, so they need your go-ahead and a test run)
1. Split the 2020-07-01 schedule at 2021-01-01 (0.00325% assumed, then 0.00345% from FA46730).
2. A per-component evidence status (VERIFIED, EXTRACTED_UNVERIFIED, ASSUMED, UNAVAILABLE, NOT_APPLICABLE) in the schedule schema, loader and calculator output, and a schedule is VERIFIED only when every component in it is. An owner's approval of an assumption authorises a modelling choice; it never makes it VERIFIED.
3. Mark the DP charge before 2024-10-01 as ASSUMED with the 13.50 evidence recorded, the pre-2020 stamp duty as ASSUMED, and service tax as UNAVAILABLE.
4. Boundary tests: 2017-06-30/07-01, 2020-06-30/07-01, 2020-12-31/2021-01-01, 2022-07-17/18, 2023-03-31/04-01, 2024-09-30/10-01, 2026-02-28/03-01; one DP charge for several sales of one scrip on one day, two for two scrips; paper-trading path included.
5. Fetch and save: the SEBI circular of 2022-07-18, CDSL's DP charge circulars (to date the Rs 13.50 to Rs 13 change), Zerodha's charge page as of 2020 and 2021 (Wayback), and the account scope (`RESIDENT_INDIVIDUAL_RETAIL`) as an explicit field.

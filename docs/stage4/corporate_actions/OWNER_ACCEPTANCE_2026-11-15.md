# Owner acceptance of six provisional corporate actions (2026-11-15)

**Decision (owner, 2026-11-15):** the six exchange-derived factors below cannot be verified from an independent source, and are ACCEPTED for use in backtests.
NMDC was accepted last, later the same day, after the further look recorded at the end. This is an acceptance, not a verification: the database status stays `provisional`.

## What acceptance does and does not change

* Research-mode backtests already apply provisional factors and list them in the run record (`docs/adjustment-policy.md`). Nothing else is needed for them to be used.
* Strict mode, and anything that supports promotion beyond research, still treat these actions as unverified and still refuse or block them. The owner's acceptance does not
  lift that, and no code was changed to make it so.
* No resolution row was written and no factor was edited.

## Accepted (factor from the exchange's own price on the ex-date; no independent source gives the number to the paisa)

| Stock | Ex-date | Kind | Factor | Web check, 2026-11-15 |
|---|---|---|---|---|
| ABB | 2019-12-20 | demerger | 0.89702 | Ex-date and ratio (1 APPSIL for 5 ABB) confirmed; BSE traded about Rs 1,280 that day. Base price 1324.00 not found in print. Our own file's low of 1257.80 is exactly 95% of 1324.00, which supports it. |
| PEL | 2019-12-30 | rights | 0.97614 | Not searched: NSE circular and issuer terms already agree (circular AF 0.976143 is the six-decimal rounding of the exact factor). |
| GMRAIRPORT | 2022-01-11 | demerger | 0.90299 | The NSE circular CMTR50943 confirms the rule used: after price discovery the base price is the discovered price. The number itself was not found in print. |
| MOTHERSON | 2022-01-14 | demerger | 0.83028 | Ex-date confirmed; press gives the previous NSE close as Rs 234.80, the same as our file, and a fall of up to 22% to about Rs 182.65. Discovered price not found in print. |
| PEL | 2022-08-30 | demerger | 0.54765 | Press gives a BSE ex-demerger open of Rs 1,050 against a previous close of Rs 1,935; our NSE figure is 1055.05 on a previous close of 1926.50. Consistent, not independent. |

Sources searched: Business Standard, ICICI Direct, Zee Business, IIFL, Trendlyne, NSE circular CMTR50943.

## NMDC (2022-10-27, demerger of NMDC Steel): ACCEPTED by the owner after the further look below

Stored factor 0.70554 = NSE's discovered price 92.25 over the previous close 130.75. What the web adds:

* Business Standard reported that NMDC rose 14.46% to Rs 107.25 on the ex-date. 107.25 / 1.1446 = 93.70, so the press figure of "a base near 93.70" is the BSE's own
  discovered price, a different exchange's auction, as the stored note already says.
* On NSE the same day the stock opened 92.25, high 109.05, closed 104.30: +13.06% on a 92.25 base. Consistent with 92.25 being NSE's base.
* The old flag "suspected incorrect, stored 0.7914" belonged to the earlier gap-era estimate. That estimate was superseded by the exchange-derived 0.70554.
* The BSE-based factor would be about 0.7166, 1.6% away. Which exchange's price should drive an NSE-traded stock's adjustment is the open question. The NSE circular for that day
  was not retrieved, so the NSE base price is still unconfirmed from the original source.

**Owner decision (2026-11-15, later): ACCEPT it,** with the stored NSE-based factor 0.70554 (NSE's own price for an NSE-traded stock). The BSE-based figure (about 0.7166) is recorded above as a known 1.6% uncertainty; the original NSE circular is still not retrieved, so the status stays `provisional` like the other five.

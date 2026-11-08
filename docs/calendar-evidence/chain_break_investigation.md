# PREVCLOSE chain breaks: 1999-10-25 and 2001-07-02 (status: UNEXPLAINED, kept as findings)

| Date | Common EQ symbols | PREVCLOSE == earlier-day CLOSE | Earlier session |
|---|---|---|---|
| 1999-10-25 | 1,135 | 192 (17%) | Fri 1999-10-22 |
| 2001-07-02 | 586 | 238 (41%) | Fri 2001-06-29 |

What was tested (stored bhavcopy only, no outside source):
- PREVCLOSE of the break day vs the previous session's CLOSE, LAST, OPEN, HIGH, LOW and traded-value/quantity
  (VWAP): CLOSE matches most often (175/1,101 and 238/584); no other field explains it.
- PREVCLOSE vs the CLOSE of each of the 8 sessions before the break: none exceeds 16% / 41%.
- Mismatches are small and two-sided on 1999-10-25 (ratios 0.99-1.03) and large on 2001-07-02
  (e.g. ABBOTTLAB 154.35 vs 524, ABBALPO 35.45 vs 20), so this is not one corporate-action factor.

Conclusions that DO hold:
- Both dates have a dated file, so trading on them is confirmed. The breaks do not change that.
- Both breaks sit between a Friday and the following Monday, so no closure inference in the ledger
  depends on either chain.
- PREVCLOSE on these two dates must not be used as an adjustment or price-continuity input.

Not established: why NSE's PREVCLOSE differs. Candidates (settlement-cycle changes around 2001-07-02,
a re-basing) are untested hypotheses. Resolving this needs an NSE notice for those dates; it is not
a blocker for the strategy work.

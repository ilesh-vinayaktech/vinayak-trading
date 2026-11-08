# Stage 4 pre-registration: Nifty 200 Trend-Filtered Momentum  (DRAFT, NOT REGISTERED)

Status: proposal for owner confirmation. Registering (validation/registry.register) fixes everything
below, starts the trial counter and fixes the holdout. Nothing here has been run.

## Hypothesis
Within Nifty 200 members, stocks with the strongest 6-12 month price momentum that are also in their own
uptrend, held only while market breadth is healthy, earn a higher risk-adjusted return after costs than
(a) buy-and-hold Nifty 200 Gross TRI and (b) plain 12-1 momentum. Expected failure mode: momentum
crashes at regime turns, which the breadth filter may or may not mitigate.

## Fixed rules (not tuned)
- Market NSE equities, daily bars, long-only, no leverage, no pyramiding, equal weight, cash when filtered out.
- Universe: Nifty 200 members on the rebalance date from `members_on(day, known_on=day)` (point-in-time).
  Eligibility: at least 252 prior sessions of bars. No liquidity screen in v1 (added only by a new version).
- Rebalance: first session of each month, decision on the prior close, executed by the existing
  next-session model.
- Score = total return over [t-L, t-21 sessions] (skip the latest month). Rank descending.
- Stock trend filter: close above its own SMA(S).
- Market filter: fraction of eligible members closing above their own SMA(200) at least 50%; below that, hold cash.
  (Breadth, not the index series, so the strategy still sees data only through Context.)
- Benchmark: Nifty 200 Gross TRI. Baseline: plain 12-1 momentum, top 20, same universe and costs.
- Adjustment basis: split/bonus adjusted prices; total return reported separately.

## Parameter grid (12 trials, the whole search)
| Parameter | Values |
|---|---|
| L, momentum lookback (sessions) | 126, 189, 252 |
| N, holdings | 20, 30 |
| S, stock trend SMA (sessions) | 100, 200 |

## Evaluation
- Data snapshot frozen at the last stored bar (2026-11-06) and the dataset hash recorded.
- Warm-up: 252 sessions, so the first signal is about 2020-10. Research window then runs to the holdout.
- Holdout: bars on and after 2025-05-01 (about the last 25% of the usable window), opened once, at the end.
- Walk-forward on the research window only: anchored, train at least 3 years, test 1 year, embargo 21 sessions.
  With about 4.5 research years this gives only 1-2 test folds: stated up front, it limits what can be proven.
- Costs: versioned schedule; also 2x costs. Gates and thresholds as in `config/validation_thresholds.json`.

## Not decided by me; owner please confirm or change
1. The signal, grid, filters and the 50% breadth rule above.
2. Holdout start 2025-05-01 and the 3-year minimum train (short history makes any choice weak).
3. Whether to proceed on a limited-history universe (see readiness) or first build the data it needs.

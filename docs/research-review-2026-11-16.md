# Research pipeline review: why every strategy fails, and how to find the highest-return one

Date: 2026-11-16. Written for the owner. Nothing in the code or the data was changed for this review; every number below was read from the
development database (studies, validation reports, alpha hypotheses, trial results) or from the code as it stands at this commit.

**Goal (owner):** find the strategy that gives the maximum return.

---

## 1. Short answer

Yes, part of the problem is the way we test, not only the strategies. Seven of the issues below are mistakes or settings that
make the result worse than it should be; the others are things we have not built yet.

The four that matter most:

1. **The deflated Sharpe gate is judging every strategy against all the other unrelated strategies we ever tried.** The best
   strategy so far (ALPHA_VOL_20D_H20) has an out-of-sample Sharpe of 1.14. Its deflated Sharpe is 0.48 (needs 0.95) because the
   "luck bar" is computed from the spread of Sharpes across *every* trial in family 1: paper tests, screeners, broken early runs,
   a different 3-year window, daily strategies that lose money. Measured against its own study's spread, the same strategy
   scores about **0.96, a pass**. (Section 3.1.)
2. **The 25% drawdown cap in the validation thresholds conflicts with what you decided on 2026-11-15** ("maximum drawdown is
   configured PER TRADE, not one account-wide number"). The cap was set on 2026-11-12 and was never updated. In the same test
   period the benchmark itself fell 38%. Two strategies failed on this cap alone. (Section 3.3.)
3. **We looked for signals in the same years we then used to "test" them.** Alpha discovery used 2020-10 to 2024-12. The
   strategy studies' out-of-sample period is about 2018-08 to 2022-12 and their inner holdout is 2023-2024. So roughly two thirds
   of the "out-of-sample" days, and all of the inner holdout, were already seen when the features were chosen. (Section 3.4.)
4. **Momentum, the factor with the strongest record for *returns* in Indian large and mid caps, was thrown out by the
   discovery step,** because that step used only about 3 to 4 years of data and a very strict multiple-testing rule. 12-month
   momentum at a 60-day horizon had a rank IC of +0.051 (t = 2.67) and was rejected. What survived are mostly *low-volatility*
   and *short-term reversal* signals, which are defensive: they tend to give a smoother ride, not the highest return.
   (Sections 3.5 and 3.7.)

Fixing 1 and 2 needs a decision from you, not new research. Fixing 3 and 4 is a rerun with a better setup. Section 5 is the
plan, ordered.

---

## 2. What we actually ran

| Step | Result |
|---|---|
| Features | 35 defined; 27 USABLE, 8 fundamental ones still DRAFT (coverage) |
| Alpha discovery batch 1 | 108 tests (27 features x 4 horizons) on **all ~2,600 stocks**, 2020-10 to 2024-12; 22 CANDIDATES |
| Alpha discovery batch 2 | 108 tests on the **200 most traded stocks each day**; 6 CANDIDATES |
| Multiple testing | Bonferroni over all 216 tests ever run (a 5% test needs p < 0.00023, about t > 3.7) |
| Strategy definitions | 16, generated from batch 1 candidates (one feature each, fixed priors: hold the top 20%, sell in the wrong half, 20 stocks, equal weight) |
| Studies | 2016-01 to 2022-12 research window, inner holdout 2023-2024, large + mid caps, Rs 1 lakh, Zerodha delivery costs, 9-trial grid each |
| Verdicts so far | 6 judged, 6 failed |

Results of the judged studies (averages over the 9 trials, research window):

| Definition | Avg CAGR | Best CAGR | Avg Sharpe | Avg worst drop | Verdict, failed on |
|---|---|---|---|---|---|
| ALPHA_DIST_SMA_50D_H1 (daily) | 11.2% | 27.9% | 0.42 | -69% | costs, drawdown, benchmark, stability |
| ALPHA_DIST_SMA_50D_H5 (weekly) | 24.6% | 36.2% | 0.79 | -59% | drawdown 43.7%, deflated Sharpe, overfitting probability, window share |
| ALPHA_MAX_DRAWDOWN_60D_H1 (daily) | n/a | n/a | n/a | n/a | failed (not analysed here) |
| ALPHA_VOL_20D_H20 (monthly) | 19.7% | 26.3% | 1.43 | -27% | **only** deflated Sharpe 0.48 and overfitting probability 0.39 |
| ALPHA_VOL_60D_H20 (monthly) | 21.1% | 27.4% | 1.49 | -27% | deflated Sharpe 0.51, overfitting probability 0.69, drawdown 32.6% |

For reference, the benchmark in the same out-of-sample period: Sharpe 0.87, worst drop 38%.

So the two monthly low-volatility strategies are genuinely decent: they beat the benchmark after twice the costs, at three times
the capital, with a smaller drawdown than the index. They fail on the "is this luck?" checks, and section 3.1 shows those checks are
being computed against the wrong reference.

---

## 3. Findings

Each finding says what is wrong, the evidence, what it costs us, and what to do. **None of them has been changed.**

### 3.1 The deflated Sharpe uses the wrong reference (biggest single issue)

**What happens.** The deflated Sharpe asks: "after N tries, how high would the best Sharpe be by luck alone?" It needs two
inputs: N, and how spread out the tried Sharpes are. The code takes both from the **research family**
(`registry.deflation_trials`). Every study, including all 16 definitions, was registered in family 1, *"Studies registered before
research families"*, which is a catch-all.

**Evidence.** Family 1 holds 74 trials: 67 from definitions, 4 screener, 3 trend-pullback (paper tests). It includes:
- 15 trials of ALPHA_VOL_20D_H20 on a **different window** (2020-2023, studies 11 and 12), with Sharpes of 1.4 to 2.1;
- 7 trials from runs that **crashed on the two engine bugs** we later fixed (studies 16, 18-21);
- 6 trials of study 11, whose `entry_share` knob **did nothing** (all three values gave identical results);
- daily strategies that lose money.

The spread of those Sharpes is about 0.47 a year. With N = 74 that sets the luck bar at an annual Sharpe of **1.14**, exactly the
best strategy's own out-of-sample Sharpe, hence a deflated Sharpe of 0.48.

Re-computed by hand for ALPHA_VOL_20D_H20 (same formula, normal returns assumed, 882 out-of-sample days):

| Reference used for the spread | N | Spread (annual) | Luck bar (annual Sharpe) | Deflated Sharpe |
|---|---|---|---|---|
| Family 1, as now | 74 | 0.47 | 1.14 | **0.50** (stored: 0.484) |
| This study's own 9 trials | 9 | 0.13 | 0.19 | **0.96** |
| Its own spread, but N = 54 (all 6 judged definition studies) | 54 | 0.13 | 0.29 | **0.94** |

**Cost.** This one setting turns a passing strategy into a failing one. It will get worse with every study we add, so the
pipeline as configured can never pass anything.

**What to do (needs your OK, it is a policy change).**
- One research family per hypothesis (for example "low volatility, monthly"), not one catch-all family.
- Count only trials that ran on the same window and finished (not crashed runs, not identical duplicates).
- Keep N honest: every *distinct* configuration tried for that hypothesis, across all its studies, still counts.

This is still strict: N keeps growing with every variant we try for the same idea, which is the point of the deflated Sharpe.

### 3.2 The overfitting-probability gate is not meaningful on a 9-variant grid of near-twins

**What happens.** The probability of backtest overfitting (CSCV) splits the history into 8 blocks and asks how often the variant
that looks best in one half ranks below the middle in the other half.

**Evidence.** Our 9 variants differ only in the number of stocks (10, 20, 30) and the exit share (30, 50, 70). They are highly
correlated, so their ranking flips almost at random from block to block: PBO 0.39 and 0.69. Yet the plateau check, which asks the
same question more directly ("does a neighbouring setting lose much?"), passes: 17-18% Sharpe lost, limit 30%.

**Cost.** A gate that is close to a coin flip fails good strategies about half the time.

**What to do.** Either compute PBO across genuinely different candidates (different features or rules within one family), or
replace it for small grids with a bootstrap confidence interval on the out-of-sample Sharpe (the code already has
`stationary_bootstrap`). Needs your OK: it is a threshold policy.

### 3.3 The drawdown cap contradicts your decision of 2026-11-15

**Evidence.** `config/validation_thresholds.json` (confirmed 2026-11-12): `owner_max_drawdown: 0.25`, an account-wide 25%. On
2026-11-15 you said maximum drawdown is per trade (now `Limits.max_trade_loss`, 2% by default, used by the paper runner). The
validation cap was never revisited. In the out-of-sample period the benchmark fell 38%; a fully invested long-only portfolio of
Indian stocks will usually fall more than 25% in a crash like March 2020.

There is a second gate that already handles drawdown sensibly: no more than 1.25 times the benchmark's drawdown. ALPHA_VOL_60D_H20
fell 32.6% against the benchmark's 38%, so it passes that one and fails only the fixed 25%.

**What to do (your decision).** Either keep a fixed account cap (then strategies need a cash filter, see 3.7), or rely on the
"relative to benchmark" gate plus the per-trade stop. Note the thresholds file says a change applies to *later* studies, so the
affected studies would be run again under the new version.

### 3.4 Discovery and testing overlap (look-ahead in the research process, not in the code)

**Evidence.** Discovery window: 2020-10-01 to 2024-12-31 (730 to 1,052 observation days per test). Study walk-forward: 2 years to
train, 6 months to test, starting 2016-08 (no stocks are usable before that, see 3.8), so out-of-sample runs about 2018-08 to
2022-12. Inner holdout: 2023-2024.

So 2020-10 to 2022-12 (about 560 of the 882 out-of-sample days) and all of 2023-2024 were part of the data that *chose* the
features. The code never looks ahead; the *researcher* did, because we picked features knowing how they did in those years.

**Cost.** The out-of-sample numbers are optimistic. They still failed, but a pass would have been weaker evidence than it looks.
The inner holdout 2023-2024 is not clean for these 16 definitions.

**What to do.** Discover on 2016-2019 only (features need computing back to 2016; the price data is there from 2016), then
validate on 2020-2022 and keep 2023-2024 as the inner holdout. Or skip discovery for factors chosen *in advance* from published
research (momentum, low volatility, quality) and spend the evidence on validation.

### 3.5 Discovery is too short and too strict for slow, high-return factors

**Evidence.**
- Features are stored only from 2020-10 (first run month), so every test has 3 to 4 years of data.
- Horizons tested: 1, 5, 20 and 60 days. Momentum works over months.
- Bonferroni over all 216 tests treats the same feature at 4 horizons as 4 independent tests. They are not (a 20-day return
  overlaps a 60-day one), so the bar is higher than needed.
- 12-month momentum (`ret_252d`) at 60 days: IC +0.051, t = 2.67, REJECTED. `ret_120d` at 60 days: +0.036, t = 2.75, REJECTED.
  52-week-high distance (`dist_high_252d`) at 60 days: +0.041, t = 2.03, REJECTED.
- Almost every CANDIDATE has a **negative** IC: low volatility, low recent return (short-term reversal), low distance from the
  50-day average. These are real effects, but they are the defensive side of the market.

**Cost.** The factor most associated with high returns in Indian large and mid caps (NSE runs a Nifty200 Momentum 30 index on
it) never reached a strategy.

**What to do.** Compute features from 2016; add 120- and 250-day horizons; control the false-discovery rate with Holm or
Benjamini-Hochberg over *families of correlated tests* rather than Bonferroni over everything; and test pre-registered factors
separately from the open search.

### 3.6 The strategies were discovered on a different universe from the one they trade

**Evidence.** The 16 definitions came from batch 1, which tested all ~2,600 stocks, including small and illiquid ones. The
studies trade the AMFI large + mid caps (about 250 names). Batch 2 (200 most traded names, close to the traded universe) found only
6 candidates, and most of them are 1-day signals that costs destroy.

**Cost.** Short-term reversal and volatility effects are much stronger among small, illiquid stocks; part of batch 1's evidence
does not apply to the stocks we can trade.

**What to do.** Run discovery on the same universe the strategies trade (large + mid, point in time).

### 3.7 The strategies are single-factor and the objective is Sharpe, not return

**Evidence.** Each definition uses one feature with fixed priors. The gates reward Sharpe (risk-adjusted), not CAGR.
Low-volatility strategies score well on Sharpe and lose on raw return. The highest average CAGR so far is the weekly
ALPHA_DIST_SMA_50D_H5 (24.6%, best variant 36.2%), which also had the worst drawdown (59%).

**What to do (for maximum return).**
- Build multi-factor rules: momentum ranked inside a quality or low-volatility filter is the classic combination (for example,
  hold the strongest 12-month momentum names among those not in the most volatile third).
- Add an index-trend cash filter (out of the market when the index is under its 200-day average). This is the usual way to cut
  the drawdown of a long-only strategy, and it is what a fixed 25% cap would need.
- Fewer, stronger positions (10 to 15) raise return, and the drawdown with it.
- Use the sizing the language already has (`INVERSE_VOLATILITY`) to keep drawdown in check while chasing return.
- Pick an explicit objective, for example "highest CAGR subject to drawdown no worse than the benchmark and Sharpe above 0.8",
  and decide it *before* looking at results.

"Maximum return" with no constraint always ends in the most concentrated, most leveraged, most overfitted variant. The gates are
there to stop that, so the right goal is the highest return that still passes them.

### 3.8 Survivorship and an empty start to the research window

**Evidence** (study 22 universe coverage):
- 2016-01 to 2016-07: **0 usable stocks.** A stock needs 252 sessions of Kite history first, so the effective start is 2016-08.
- 2016-08 to 2018-07: the "traded value" stand-in ranks only stocks that **have Kite history today**, so it leaves out companies
  that later delisted or merged. That is survivorship bias, accepted on purpose (`accept_survivorship_bias: true`).
- From 2018-08 the AMFI lists apply; 231 to 243 of their 250 names are usable (the rest were delisted or merged).

**Cost.** Early-year returns are a little optimistic.

**What to do.** Bring in bhavcopy history for names that delisted (the NSE source covers them), or start the research window at
2018-08 where the real lists begin.

### 3.9 The backtest does not apply the stop-loss the paper account applies

**Evidence.** `trade_stops` / `max_trade_loss` are used only by `paper/runner.py`; neither the backtest engine nor the study
runner uses them. The 5-day re-buy cooldown is also paper-only.

**Cost.** We validate one strategy and paper-trade a different one: the paper account sells on a 2% loss, the backtest never does.
A 2% stop on a monthly low-volatility strategy will trigger often and change its results a lot, in either direction.

**What to do.** Put the per-trade stop and cooldown into the backtest engine as study settings, so the validated strategy is the
one that trades.

### 3.10 Smaller issues

- **Wasted, counted trials.** Study 11's `entry_share` grid was a no-op, and every crashed attempt is a counted trial. Both push the
  deflated Sharpe bar up (3.1).
- **The grid tunes only portfolio knobs** (number of stocks, exit share). The signal itself (lookback, entry share) is fixed. That
  is defensible as "priors only", but it means the plateau and PBO checks see near-identical variants.
- **Fundamentals cannot be used in a strategy yet.** The interpreter refuses filing-based features, and 8 fundamental features are
  DRAFT for coverage. `fund_operating_margin` had the strongest IC of any test (-0.082 at 60 days). The *negative* sign (lower
  margin, higher later return) is surprising and should be checked for a data or coverage artefact before anyone trades on it.
- **History-dependent features are refused** (RSI, ATR): 5 of the 8 refused candidates are those.
- **"Regimes" are calendar years**, a stand-in. Real regime labels (bull, bear, sideways by index trend) would be more
  informative.
- **The daily (1-day) definitions are costly to test** (they re-rank every stock every day) and cannot survive costs anyway. Their
  studies take over an hour each and add counted trials.

---

## 4. What is right and should stay

- The engine is careful: decisions at the close, fills at the next open, real Zerodha costs, a liquidity cap, corporate actions
  and ISIN changes handled, the two bugs found this week now fixed and tested.
- Walk-forward selection, 2x costs and 3x capital stress, benchmark comparison, concentration checks: these are the right gates.
- Every trial is recorded and the global holdout (2025 onward) is untouched for every strategy. That holdout is still a clean,
  one-time test.
- Thresholds were fixed *before* results. Keep that discipline: any change from this review should be a new threshold version
  applied to new studies.

---

## 5. Recommended plan, in order

**A. Decisions only, no new code (you):**
1. Drawdown: replace the fixed 25% account cap with the relative-to-benchmark gate plus the per-trade stop, or keep 25% and require
   a cash filter. (3.3)
2. Deflated Sharpe reference: one family per hypothesis, count only finished trials on the same window. (3.1)
3. PBO: keep it only for grids of genuinely different candidates; otherwise use a bootstrap interval on out-of-sample Sharpe. (3.2)
4. Objective: "highest CAGR that passes every gate". (3.7)

**B. Make the evidence clean (code, then rerun):**
5. Compute features from 2016-08; rerun alpha discovery on 2016-08 to 2019-12, on the large + mid universe, with 120- and 250-day
   horizons and a false-discovery-rate control by correlated family. (3.4, 3.5, 3.6)
6. Put the per-trade stop and cooldown into the backtest as study settings. (3.9)
7. Stop counting crashed and duplicate trials; drop no-op grid knobs. (3.10)

**C. Strategies aimed at return:**
8. Pre-register three return-oriented rules and test them under the new setup: 12-month momentum; momentum inside a
   low-volatility filter; momentum with an index-trend cash filter. (3.7)
9. Re-validate ALPHA_VOL_20D_H20 under the corrected reference. It is the best candidate so far. Only if it passes every gate,
   decide whether to spend its one-time holdout. (3.1)

**D. Later:**
10. Let strategies read fundamentals (quality: ROE, ROCE, debt) after the old-feed crawl fills the pre-2025 gaps; check the odd
    sign of operating margin first.
11. Real regime labels; history-dependent features (RSI, ATR) in definitions.

The 16-definition run now in progress will keep going. Its remaining verdicts are still useful as a baseline, but under the current
reference (3.1) none of them can be expected to pass.

# PBO diagnostic: where the overfitting probability comes from (2016-2022 studies, new setup)

Date: 2026-11-16. Written for the owner. Produced by `scripts/pbo_diagnostic.py` (read-only; it repeats the gate's own method, keeps every partition and takes the number apart).
Nothing in the gates or thresholds was changed. The numbers are the real ones from the database; the reading is mine.

## What the report answers (your six questions)

1. PBO for each of the nine variants: the table "PBO when it wins" gives each variant's share of its own in-sample wins that ended at or below the out-of-sample median. A variant that never wins in sample has no PBO of its own (shown as "-").
2. Distribution across all 70 partitions: logit quantiles, the count of the in-sample winner's out-of-sample rank (1 = worst of 9) and the mean Sharpe in sample vs out of sample.
3. How often each variant ranks first in sample: "wins in sample".
4. Its out-of-sample rank: "out-of-sample rank when it wins" and "mean out-of-sample rank overall".
5. Whether poor ranks sit in particular market periods: the by-period table (8 blocks of about 10 months; the average variant's annual return in each block, and the PBO when that block is out of sample or in sample).
6. Whether a few partitions drive it: how many partitions would have to turn good to reach 0.2, and how the number moves with the number of blocks (4, 6, 8, 10).

## What it shows

| Study | PBO (8 blocks) | Partitions that would have to turn good | PBO at 4 / 6 / 8 / 10 blocks | Winner's out-of-sample Sharpe vs the average variant (per day) |
|---|---|---|---|---|
| MOMENTUM_12M_M | 0.79 | 41 of 70 | 0.83 / 0.85 / 0.79 / 0.87 | 0.066 vs 0.071 |
| MOMENTUM_LOWVOL_M | 0.37 | 12 of 70 | 0.50 / 0.10 / 0.37 / 0.10 | 0.076 vs 0.073 |
| MOMENTUM_TREND_M | 0.81 | 43 of 70 | 1.00 / 0.80 / 0.81 / 0.86 | 0.057 vs 0.061 |
| ALPHA_VOL_20D_H20 | 0.57 | 26 of 70 | 0.67 / 0.55 / 0.57 / 0.75 | 0.101 vs 0.101 |
| ALPHA_VOL_60D_H20 | 0.73 | 37 of 70 | 0.67 / 0.90 / 0.73 / 0.77 | 0.088 vs 0.090 |

**1. The high PBO is not a few bad partitions and not particular years.** For MOMENTUM_12M_M, 55 of 70 partitions fail and the PBO is 71% to 86% whichever block is held out: no market period carries it
(2018-19 was a losing block, -12% for the average variant, and it is no worse than the 2020-21 block that returned +77%). It is a property of the whole set of variants.

**2. In sample, the winner is not better than the average variant out of sample.** For four of the five studies the in-sample winner's out-of-sample Sharpe equals or is below the average variant's (0.066 vs 0.071,
0.101 vs 0.101). Choosing among the nine settings added nothing. That is what PBO above 0.5 means: the in-sample ranking of the variants is noise.

**3. That is a finding about choosing between variants, not about whether the strategy has an edge.** Every variant of MOMENTUM_12M_M earned between 17% and 41% a year and a Sharpe near 1.1 after costs. The nine variants
differ only in the number of stocks (10 / 20 / 30) and the exit share (30 / 50 / 70), so they are one strategy with small knob differences, and their ranking flips as the periods change. PBO is designed to ask whether the
variant you would pick is the right one; here no variant is reliably better than the rest.

**4. The one place where the knobs DO matter is MOMENTUM_LOWVOL_M, and it shows a real effect.** Variants with 30 positions win in sample 60% of the time and rank 7 to 8 of 9 out of sample; variants with 10 positions rank 2.5 to 3.6.
The in-sample winner holds up (PBO 14% on the partitions it wins). The study's PBO of 0.37 comes from the minority of partitions (about 14) where a 10 or 20 position variant, or the 30%-exit variant, wins in sample and then ranks low.
Its PBO also moves a lot with how the history is cut (0.10 at 6 and 10 blocks, 0.50 at 4, 0.37 at 8), so 0.37 is a fragile number in both directions.

## What I think

- **The strategies are not showing "no edge"**: all five have out-of-sample Sharpe of about 1.0 to 1.6 after costs and beat the index. The gate that fails them is testing something else: whether tuning the portfolio knobs on the past picks a variant that stays best.
- **If we do not tune, there is nothing to overfit.** The honest fix is to pre-register ONE configuration per strategy (the priors we already wrote down: 20 stocks, entry 20%, exit 50% for the generated ones; 15 for the momentum ones), and use the nine-variant grid only as a robustness check (the plateau test). PBO then applies only when a study really chooses among genuinely different candidates. This is the direction the review already pointed to (section 3.2).
- **That is a policy change made after seeing results**, so it must apply to a NEW round (new pre-registered single configurations, new studies, same costs and stop), not be used to re-judge the studies already run. The global holdout must stay closed until a strategy passes under the rule that was fixed before it was run.
- **Do not move the 0.9 near-twin cut-off now.** MOMENTUM_12M_M's variants correlate 0.87, just under it; moving the line to rescue one result would be exactly the tuning PBO is meant to catch.

## The full reports

## MOMENTUM_12M_M v1 2016-2022 stop2

PBO 0.79 over 70 partitions (55 with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, 41 of them would have to turn good.

Sensitivity to how the history is cut (blocks -> PBO): 4 -> 0.83, 6 -> 0.85, 8 -> 0.79, 10 -> 0.87

### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)

| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |
|---|---|---|---|---|---|---|---|
| exit_share 30, max_positions 20 | 21 | 30% | 5.2 | 48% | 0.089 | 0.063 | 7.0 |
| exit_share 50, max_positions 30 | 18 | 26% | 3.2 | 83% | 0.091 | 0.061 | 6.4 |
| exit_share 50, max_positions 10 | 9 | 13% | 2.1 | 100% | 0.059 | 0.080 | 4.7 |
| exit_share 70, max_positions 10 | 7 | 10% | 2.1 | 100% | 0.082 | 0.066 | 4.4 |
| exit_share 30, max_positions 30 | 6 | 9% | 4.2 | 83% | 0.087 | 0.063 | 5.7 |
| exit_share 70, max_positions 20 | 5 | 7% | 1.8 | 100% | 0.081 | 0.062 | 5.2 |
| exit_share 70, max_positions 30 | 3 | 4% | 3.0 | 100% | 0.044 | 0.093 | 4.4 |
| exit_share 30, max_positions 10 | 1 | 1% | 1.0 | 100% | 0.084 | 0.057 | 3.2 |
| exit_share 50, max_positions 20 | 0 | 0% | - | - | - | - | 3.9 |

### 2. Distribution over partitions

- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min -2.20, 25% -1.39, median -0.85, 75% 0.00, max 1.39
- Out-of-sample rank of the in-sample winner (1 = worst of 9): 1: 14, 2: 15, 3: 11, 4: 8, 5: 7, 6: 6, 7: 7, 8: 2, 9: 0
- Mean per-day Sharpe of the in-sample winner: in sample 0.082, out of sample 0.066; the average variant out of sample 0.071

### 5-6. By period: is the instability in particular years?

| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |
|---|---|---|---|
| 2017-01 to 2017-10 | 44.7% | 77% | 80% |
| 2017-10 to 2018-07 | 33.4% | 83% | 74% |
| 2018-07 to 2019-04 | -12.2% | 80% | 77% |
| 2019-04 to 2020-01 | 9.0% | 77% | 80% |
| 2020-01 to 2020-10 | 1.3% | 86% | 71% |
| 2020-10 to 2021-07 | 76.9% | 80% | 77% |
| 2021-07 to 2022-03 | 38.0% | 71% | 86% |
| 2022-03 to 2022-12 | 11.3% | 74% | 83% |

## MOMENTUM_LOWVOL_M v1 2016-2022 stop2

PBO 0.37 over 70 partitions (26 with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, 12 of them would have to turn good.

Sensitivity to how the history is cut (blocks -> PBO): 4 -> 0.50, 6 -> 0.10, 8 -> 0.37, 10 -> 0.10

### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)

| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |
|---|---|---|---|---|---|---|---|
| exit_share 70, max_positions 30 | 42 | 60% | 7.2 | 14% | 0.091 | 0.086 | 7.9 |
| exit_share 30, max_positions 30 | 18 | 26% | 4.2 | 78% | 0.088 | 0.063 | 6.5 |
| exit_share 50, max_positions 30 | 3 | 4% | 8.0 | 0% | 0.099 | 0.075 | 7.5 |
| exit_share 50, max_positions 10 | 2 | 3% | 3.0 | 100% | 0.110 | 0.043 | 3.6 |
| exit_share 50, max_positions 20 | 2 | 3% | 2.0 | 100% | 0.094 | 0.047 | 3.8 |
| exit_share 70, max_positions 10 | 2 | 3% | 1.0 | 100% | 0.094 | 0.030 | 2.5 |
| exit_share 30, max_positions 20 | 1 | 1% | 6.0 | 0% | 0.066 | 0.081 | 5.8 |
| exit_share 30, max_positions 10 | 0 | 0% | - | - | - | - | 2.9 |
| exit_share 70, max_positions 20 | 0 | 0% | - | - | - | - | 4.5 |

### 2. Distribution over partitions

- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min -2.20, 25% -0.41, median 0.85, 75% 1.39, max 2.20
- Out-of-sample rank of the in-sample winner (1 = worst of 9): 1: 5, 2: 7, 3: 3, 4: 4, 5: 7, 6: 6, 7: 12, 8: 12, 9: 14
- Mean per-day Sharpe of the in-sample winner: in sample 0.091, out of sample 0.076; the average variant out of sample 0.073

### 5-6. By period: is the instability in particular years?

| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |
|---|---|---|---|
| 2017-01 to 2017-10 | 34.3% | 34% | 40% |
| 2017-10 to 2018-07 | 33.3% | 29% | 46% |
| 2018-07 to 2019-04 | -2.5% | 34% | 40% |
| 2019-04 to 2020-01 | 4.9% | 31% | 43% |
| 2020-01 to 2020-10 | 4.2% | 40% | 34% |
| 2020-10 to 2021-07 | 42.1% | 26% | 49% |
| 2021-07 to 2022-03 | 31.5% | 57% | 17% |
| 2022-03 to 2022-12 | 20.3% | 46% | 29% |

## MOMENTUM_TREND_M v1 2016-2022 stop2

PBO 0.81 over 70 partitions (57 with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, 43 of them would have to turn good.

Sensitivity to how the history is cut (blocks -> PBO): 4 -> 1.00, 6 -> 0.80, 8 -> 0.81, 10 -> 0.86

### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)

| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |
|---|---|---|---|---|---|---|---|
| exit_share 70, max_positions 30 | 17 | 24% | 2.1 | 94% | 0.074 | 0.050 | 5.3 |
| exit_share 70, max_positions 20 | 16 | 23% | 5.5 | 44% | 0.082 | 0.045 | 6.8 |
| exit_share 70, max_positions 10 | 10 | 14% | 2.4 | 100% | 0.059 | 0.065 | 4.0 |
| exit_share 30, max_positions 30 | 9 | 13% | 2.2 | 100% | 0.083 | 0.049 | 5.1 |
| exit_share 50, max_positions 30 | 6 | 9% | 4.2 | 50% | 0.062 | 0.066 | 5.5 |
| exit_share 50, max_positions 20 | 5 | 7% | 4.6 | 100% | 0.066 | 0.074 | 5.7 |
| exit_share 30, max_positions 20 | 3 | 4% | 5.0 | 100% | 0.024 | 0.106 | 5.6 |
| exit_share 50, max_positions 10 | 3 | 4% | 1.0 | 100% | 0.072 | 0.045 | 3.5 |
| exit_share 30, max_positions 10 | 1 | 1% | 2.0 | 100% | 0.016 | 0.100 | 3.5 |

### 2. Distribution over partitions

- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min -2.20, 25% -2.20, median -0.85, 75% 0.00, max 1.39
- Out-of-sample rank of the in-sample winner (1 = worst of 9): 1: 24, 2: 2, 3: 12, 4: 11, 5: 8, 6: 7, 7: 2, 8: 4, 9: 0
- Mean per-day Sharpe of the in-sample winner: in sample 0.070, out of sample 0.057; the average variant out of sample 0.061

### 5-6. By period: is the instability in particular years?

| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |
|---|---|---|---|
| 2017-01 to 2017-10 | 44.7% | 80% | 83% |
| 2017-10 to 2018-07 | 40.7% | 94% | 69% |
| 2018-07 to 2019-04 | -4.0% | 80% | 83% |
| 2019-04 to 2020-01 | -11.3% | 83% | 80% |
| 2020-01 to 2020-10 | -13.8% | 86% | 77% |
| 2020-10 to 2021-07 | 75.2% | 71% | 91% |
| 2021-07 to 2022-03 | 27.6% | 80% | 83% |
| 2022-03 to 2022-12 | 1.9% | 77% | 86% |

## ALPHA_VOL_20D_H20 v1 2016-2022 stop2

PBO 0.57 over 70 partitions (40 with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, 26 of them would have to turn good.

Sensitivity to how the history is cut (blocks -> PBO): 4 -> 0.67, 6 -> 0.55, 8 -> 0.57, 10 -> 0.75

### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)

| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |
|---|---|---|---|---|---|---|---|
| exit_share 30, max_positions 10 | 36 | 51% | 4.9 | 61% | 0.125 | 0.107 | 6.8 |
| exit_share 50, max_positions 20 | 21 | 30% | 5.9 | 24% | 0.122 | 0.103 | 7.2 |
| exit_share 30, max_positions 30 | 5 | 7% | 4.0 | 100% | 0.132 | 0.086 | 5.8 |
| exit_share 50, max_positions 10 | 3 | 4% | 3.7 | 100% | 0.113 | 0.108 | 6.2 |
| exit_share 50, max_positions 30 | 2 | 3% | 2.0 | 100% | 0.097 | 0.077 | 3.2 |
| exit_share 70, max_positions 10 | 2 | 3% | 1.0 | 100% | 0.123 | 0.060 | 3.5 |
| exit_share 30, max_positions 20 | 1 | 1% | 5.0 | 100% | 0.170 | 0.059 | 6.6 |
| exit_share 70, max_positions 20 | 0 | 0% | - | - | - | - | 4.2 |
| exit_share 70, max_positions 30 | 0 | 0% | - | - | - | - | 1.5 |

### 2. Distribution over partitions

- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min -2.20, 25% -0.85, median 0.00, 75% 0.41, max 2.20
- Out-of-sample rank of the in-sample winner (1 = worst of 9): 1: 4, 2: 5, 3: 9, 4: 9, 5: 13, 6: 20, 7: 4, 8: 2, 9: 4
- Mean per-day Sharpe of the in-sample winner: in sample 0.124, out of sample 0.101; the average variant out of sample 0.101

### 5-6. By period: is the instability in particular years?

| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |
|---|---|---|---|
| 2017-01 to 2017-10 | 34.4% | 57% | 57% |
| 2017-10 to 2018-07 | 28.0% | 51% | 63% |
| 2018-07 to 2019-04 | 14.7% | 49% | 66% |
| 2019-04 to 2020-01 | 22.9% | 51% | 63% |
| 2020-01 to 2020-10 | 16.1% | 77% | 37% |
| 2020-10 to 2021-07 | 27.2% | 57% | 57% |
| 2021-07 to 2022-04 | -2.9% | 54% | 60% |
| 2022-04 to 2022-12 | 11.0% | 60% | 54% |

## ALPHA_VOL_60D_H20 v1 2016-2022 stop2

PBO 0.73 over 70 partitions (51 with the in-sample winner at or below the out-of-sample median). To reach the allowed 0.20, 37 of them would have to turn good.

Sensitivity to how the history is cut (blocks -> PBO): 4 -> 0.67, 6 -> 0.90, 8 -> 0.73, 10 -> 0.77

### 1-4. Each variant: how often it wins in sample, and how it ranks out of sample (rank 1 = worst of the variants)

| variant | wins in sample | share | out-of-sample rank when it wins | PBO when it wins | in-sample Sharpe when it wins | out-of-sample Sharpe when it wins | mean out-of-sample rank overall |
|---|---|---|---|---|---|---|---|
| exit_share 30, max_positions 10 | 26 | 37% | 4.6 | 65% | 0.096 | 0.102 | 6.9 |
| exit_share 50, max_positions 30 | 18 | 26% | 5.1 | 67% | 0.101 | 0.095 | 6.7 |
| exit_share 70, max_positions 30 | 15 | 21% | 2.6 | 100% | 0.113 | 0.078 | 6.2 |
| exit_share 30, max_positions 20 | 5 | 7% | 2.0 | 100% | 0.115 | 0.067 | 4.9 |
| exit_share 50, max_positions 20 | 5 | 7% | 6.2 | 20% | 0.144 | 0.052 | 6.5 |
| exit_share 70, max_positions 20 | 1 | 1% | 2.0 | 100% | 0.120 | 0.047 | 4.1 |
| exit_share 30, max_positions 30 | 0 | 0% | - | - | - | - | 4.0 |
| exit_share 50, max_positions 10 | 0 | 0% | - | - | - | - | 3.1 |
| exit_share 70, max_positions 10 | 0 | 0% | - | - | - | - | 2.6 |

### 2. Distribution over partitions

- Logit of the winner's out-of-sample rank (at or below 0 counts as overfit): min -2.20, 25% -0.85, median -0.41, 75% 0.41, max 2.20
- Out-of-sample rank of the in-sample winner (1 = worst of 9): 1: 7, 2: 8, 3: 14, 4: 15, 5: 7, 6: 7, 7: 8, 8: 2, 9: 2
- Mean per-day Sharpe of the in-sample winner: in sample 0.106, out of sample 0.088; the average variant out of sample 0.090

### 5-6. By period: is the instability in particular years?

| period (block) | average variant annual return | PBO when this block is out of sample | PBO when it is in sample |
|---|---|---|---|
| 2017-01 to 2017-10 | 31.0% | 74% | 71% |
| 2017-10 to 2018-07 | 29.6% | 77% | 69% |
| 2018-07 to 2019-04 | 4.7% | 71% | 74% |
| 2019-04 to 2020-01 | 22.3% | 77% | 69% |
| 2020-01 to 2020-10 | 7.0% | 63% | 83% |
| 2020-10 to 2021-07 | 27.1% | 69% | 77% |
| 2021-07 to 2022-04 | -1.9% | 80% | 66% |
| 2022-04 to 2022-12 | 5.4% | 71% | 74% |

# TIE kill test: frozen hold rule (A) with one causal trend filter on entry
universe 521 liquid stocks, bars before 2025-01-01; costs from DB cost_schedule (zerodha DELIVERY) + slippage; order Rs 20,000; round trip on a Rs 5cr-turnover stock: 2021 0.404%, 2026 0.403%

## Pooled 2022-2024 (portfolio: max 10 positions, cash 0; daily net return %, mean [CI]); verdict uses the 99% CI of variant - A

variant  trades  mean_hold  net-mkt/trade%                  daily% folds_beat_A  exposure  variant-A daily% (99%) verdict
      A    5125       21.3           0.191 +0.075 [+0.009, +0.127]            -      1.00                     NaN     NaN
     ST    2795       28.6          -0.282 +0.044 [-0.025, +0.101]          1/3      1.00 -0.031 [-0.074, +0.009]    FAIL
     ER    3051       24.0           0.097 +0.096 [+0.017, +0.168]          2/3      1.00 +0.021 [-0.036, +0.077]    FAIL
  SLOPE    3245       26.8          -0.249 +0.075 [+0.017, +0.130]          2/3      1.00 -0.001 [-0.032, +0.027]    FAIL
  SWING    2455       28.9          -0.304 +0.083 [+0.016, +0.141]          2/3      1.00 +0.008 [-0.029, +0.046]    FAIL
 WEEKLY    3328       26.1           0.005 +0.065 [+0.009, +0.118]          0/3      1.00 -0.010 [-0.042, +0.028]    FAIL
    ALL    1051       41.0          -1.412 +0.052 [-0.024, +0.115]          1/3      0.97 -0.023 [-0.073, +0.025]    FAIL

## Per fold: compounded net portfolio return % (market = equal-weight average stock)

 year  market%     A     ST    ER  SLOPE  SWING  WEEKLY   ALL
 2022     6.86  5.34 -10.70 -0.09  11.74  10.38    3.44 -5.74
 2023    50.30 25.48  30.24 51.36  27.31  27.20   25.30 29.00
 2024    23.95 27.86  15.94 28.82  18.44  26.99   21.04 16.86

## Descriptive only: A's own trades, net-market % by filter state at entry (pooled; never a candidate filter)

filter  true_n  true%  false_n  false%
    ST    2450 -0.054     2675   0.415
    ER    1956  0.544     3169  -0.027
 SLOPE    2723 -0.144     2402   0.571
 SWING    1740  0.206     3385   0.183
WEEKLY    2946  0.192     2179   0.189
   ALL     532 -0.233     4593   0.240

## Verdicts (frozen rule; development evidence only): ST=FAIL, ER=FAIL, SLOPE=FAIL, SWING=FAIL, WEEKLY=FAIL, ALL=FAIL

# ATI regime validation (ati-f1 / ati-r1)
stocks 1769, sessions 1631, bars before 2025-01-01; forward window 20 sessions from the close of t
known regime share of stock-days: 0.667

## Per regime (forward 20-session excess return over the same-day universe mean, %)

                regime  share  mean_run      n  excess_mean%  excess_median%   hit   mfe%    mae%
        STRONG_UPTREND  0.217     6.347 409932         0.414          -2.001 0.428 14.642  -8.351
          WEAK_UPTREND  0.177     3.188 333446        -0.500          -2.671 0.392 13.953  -8.227
             DOWNTREND  0.345     9.330 650627        -0.168          -1.988 0.407 13.921  -8.742
              SIDEWAYS  0.022     1.374  40655        -0.243          -2.535 0.392 13.391  -8.289
  VOLATILITY_EXPANSION  0.069     7.737 130971        -1.176          -3.794 0.378 16.159 -11.045
VOLATILITY_CONTRACTION  0.003     1.353   5416        -1.036          -2.872 0.380 13.950  -7.403
    POTENTIAL_REVERSAL  0.169     2.614 318352        -0.506          -2.522 0.395 13.649  -8.267

## Transition matrix (row = today, column = next session; share of the row)

                        STRONG  WEAK_U  DOWNTR  SIDEWA  VOLATI  VOLATI  POTENT
STRONG_UPTREND           0.843   0.096   0.000   0.001   0.023   0.000   0.036
WEAK_UPTREND             0.121   0.687   0.006   0.034   0.012   0.005   0.136
DOWNTREND                0.001   0.004   0.894   0.019   0.003   0.002   0.077
SIDEWAYS                 0.041   0.207   0.279   0.272   0.004   0.004   0.192
VOLATILITY_EXPANSION     0.064   0.025   0.017   0.002   0.871   0.000   0.020
VOLATILITY_CONTRACTION   0.030   0.236   0.278   0.009   0.001   0.261   0.186
POTENTIAL_REVERSAL       0.041   0.155   0.162   0.017   0.005   0.002   0.618

## Mean forward excess % by regime and year

                         2019   2020   2021   2022   2023   2024
STRONG_UPTREND          0.525  0.196  0.507  0.436  0.165  0.662
WEAK_UPTREND           -1.629 -0.986  0.097 -0.603 -0.135 -0.214
DOWNTREND               0.913  0.932 -1.182 -0.343 -0.169 -0.383
SIDEWAYS               -1.110 -0.066 -0.274 -0.354 -0.145 -0.094
VOLATILITY_EXPANSION   -0.298 -2.708 -1.285 -0.721 -0.553 -0.470
VOLATILITY_CONTRACTION -1.933 -1.738 -2.419 -0.222  0.492 -1.023
POTENTIAL_REVERSAL     -0.562 -0.540 -1.034 -0.331 -0.134 -0.539

## Market regime (equal-weight index): share of sessions and mean breadth (share of stocks above EMA50)

                        share  breadth
STRONG_UPTREND          0.397    0.697
WEAK_UPTREND            0.120    0.551
DOWNTREND               0.145    0.222
SIDEWAYS                0.006    0.364
VOLATILITY_EXPANSION    0.102    0.510
VOLATILITY_CONTRACTION  0.001    0.398
POTENTIAL_REVERSAL      0.107    0.392

## K-Means (fit on 2019-2021 only, assigned to 2022-2024; features ret_5d_norm, ret_20d_norm, ret_50d_norm, atr_pct_14, vol_percentile_252, ema_20_50_spread, relative_volume, bb_width_20)

k=4: stability (adjusted Rand index, seed 0 vs 1, test rows) = 0.989
 cluster  share  excess_mean%   hit
       0  0.021        -0.879 0.401
       1  0.607         0.031 0.418
       2  0.337        -0.351 0.403
       3  0.000       -15.828 0.312

k=6: stability (adjusted Rand index, seed 0 vs 1, test rows) = 0.980
 cluster  share  excess_mean%   hit
       0  0.386        -0.104 0.413
       1  0.013        -1.205 0.395
       2  0.463         0.112 0.420
       3  0.000       -15.828 0.312
       4  0.067        -1.366 0.376
       5  0.036        -0.608 0.390

k=8: stability (adjusted Rand index, seed 0 vs 1, test rows) = 0.969
 cluster  share  excess_mean%   hit
       0  0.358        -0.005 0.417
       1  0.439         0.086 0.418
       2  0.059        -1.575 0.369
       3  0.000       -33.055 0.000
       4  0.071        -0.475 0.404
       5  0.002        -1.632 0.357
       6  0.035        -0.648 0.389
       7  0.000        -0.700 0.615


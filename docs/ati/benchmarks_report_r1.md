# ATI benchmarks and GMM (ati-f1 / ati-r1)
stocks 1769 (422 with a sector), sessions 1631, bars before 2025-01-01; forward window 20 sessions; CI level 0.9929 (Bonferroni over 7 regimes)

## Per rule regime: mean forward excess % against three benchmarks (vol-matched CI from per-date means)

                regime      n  vs_universe%  vs_vol%  vol_lo%  vol_hi%  vol_hit  n_sector  vs_sector%  vs_vol_same_stocks%
        STRONG_UPTREND 409932         0.414    0.398   -0.033    0.967    0.429    144376       0.138                0.045
          WEAK_UPTREND 333446        -0.500   -0.447   -0.677   -0.004    0.395     91567      -0.241               -0.610
             DOWNTREND 650627        -0.168   -0.098   -0.644    0.231    0.412    149124      -0.021               -0.355
              SIDEWAYS  40655        -0.243   -0.269   -0.590    0.018    0.395     10030      -0.426               -0.718
  VOLATILITY_EXPANSION 130971        -1.176   -0.388   -0.742    0.907    0.405     29951       0.334                0.275
VOLATILITY_CONTRACTION   5416        -1.036   -0.992      NaN      NaN    0.380      1245      -0.945               -1.799
    POTENTIAL_REVERSAL 318352        -0.506   -0.460   -0.716   -0.253    0.398     85359      -0.129               -0.449

## Mean vol-matched excess % by regime and year

                         2019   2020   2021   2022   2023   2024
STRONG_UPTREND          0.223  0.127  0.431  0.647  0.114  0.653
WEAK_UPTREND           -1.485 -0.862  0.040 -0.506 -0.123 -0.205
DOWNTREND               0.709  0.936 -0.593 -0.303 -0.143 -0.464
SIDEWAYS               -1.092 -0.005 -0.347 -0.340 -0.147 -0.197
VOLATILITY_EXPANSION    0.625 -1.922 -0.744  0.238  0.279  0.389
VOLATILITY_CONTRACTION -1.911 -1.774 -1.679 -0.215  0.355 -1.105
POTENTIAL_REVERSAL     -0.568 -0.400 -0.928 -0.234 -0.173 -0.571

## K-Means vs Gaussian mixture (fit 2019-2021, test 2022-2024)

kmeans k=4: stability (ARI seed 0 vs 1) = 0.989; eta2 = 0.00006; components under 1000 test rows: [3]
 cluster  n_test  vol_excess_mean%   hit
       0   25571            -0.542 0.414
       1  754199            -0.048 0.416
       2  418328            -0.036 0.416
       3      16           -15.667 0.312

kmeans k=6: stability (ARI seed 0 vs 1) = 0.980; eta2 = 0.00018; components under 1000 test rows: [3]
 cluster  n_test  vol_excess_mean%   hit
       0  479452            -0.101 0.416
       1   16091            -0.817 0.405
       2  574504             0.064 0.419
       3      16           -15.667 0.312
       4   83112            -0.244 0.411
       5   44939            -0.449 0.394

kmeans k=8: stability (ARI seed 0 vs 1) = 0.969; eta2 = 0.00021; components under 1000 test rows: [3, 7]
 cluster  n_test  vol_excess_mean%   hit
       0  444561            -0.030 0.418
       1  545697             0.048 0.418
       2   73453            -0.353 0.406
       3       9           -32.308 0.000
       4   87982            -0.329 0.411
       5    2598            -0.958 0.369
       6   43762            -0.483 0.393
       7      52            -0.941 0.596

gmm k=4: stability (ARI seed 0 vs 1) = 0.725, BIC(train sample) = -269581; eta2 = 0.00003; components under 1000 test rows: []
 cluster  n_test  vol_excess_mean%   hit
       0  105115            -0.225 0.419
       1    1869            -0.188 0.467
       2  932432            -0.054 0.415
       3  158698             0.056 0.417

gmm k=6: stability (ARI seed 0 vs 1) = 0.392, BIC(train sample) = -325800; eta2 = 0.00019; components under 1000 test rows: [3]
 cluster  n_test  vol_excess_mean%   hit
       0  802936            -0.114 0.413
       1   68365             0.222 0.445
       2  172355             0.148 0.419
       3     539            -0.144 0.492
       4  143743            -0.005 0.415
       5   10176            -1.407 0.392

gmm k=8: stability (ARI seed 0 vs 1) = 0.617, BIC(train sample) = -359143; eta2 = 0.00040; components under 1000 test rows: [3]
 cluster  n_test  vol_excess_mean%   hit
       0  251578             0.234 0.423
       1  581919            -0.198 0.411
       2   39648            -0.939 0.388
       3     173            -0.264 0.497
       4  162894             0.075 0.426
       5   12291            -0.040 0.426
       6  145144             0.129 0.418
       7    4467            -0.595 0.428

## Explained share (eta-squared) of the test-period vol-matched excess variance, and agreement with the rule regimes (k = 6)

          labels    eta2  AMI_with_rules
rule regimes (7) 0.00071             NaN
          kmeans 0.00018         0.08359
             gmm 0.00019         0.10176

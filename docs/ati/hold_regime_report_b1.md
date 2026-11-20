# ATI x hold signal: A (frozen rule) vs B (entry only in STRONG_UPTREND)
universe 521 liquid stocks, bars before 2025-01-01; costs from DB cost_schedule (zerodha DELIVERY) + slippage; order Rs 20,000; round trip on a Rs 5cr-turnover stock: 2021 0.404%, 2026 0.403%

## Per fold (test year; model trained to the end of the year two before it)

 year variant  trades  mean_hold  gross%   net%  net-market%  portfolio%  market%  exposure
 2022       A    1758     19.279   1.258  0.857        0.428       5.338    6.861     1.000
 2022       B     503     34.386   0.001 -0.400       -0.450      -4.936    6.861     0.996
 2023       A    1308     26.904   5.076  4.675       -0.588      25.485   50.303     1.000
 2023       B     516     45.161   8.085  7.685       -2.698      26.869   50.303     1.000
 2024       A    2059     19.505   2.967  2.567        0.483      27.862   23.952     1.000
 2024       B     786     33.123   3.429  3.029        0.607      17.908   23.952     1.000

## Pooled 2022-2024: per-trade net return minus the market over the trade window, %, mean [95% CI over trades in time order]

A: trades 5125, mean hold 21.3 sessions, net-market +0.191 [-0.160, +0.465]
B: trades 1805, mean hold 36.9 sessions, net-market -0.632 [-1.351, +0.063]

## Portfolio (max 10 positions, cash earns 0): daily net return, %

A daily +0.075 [+0.009, +0.127]  (exposure 1.00)
B daily +0.052 [-0.018, +0.116]  (exposure 1.00)
B - A daily -0.023 [-0.051, +0.007]

## Diagnostic: A's own trades split by the regime at their entry signal (pooled)

                        trades  net-market%
reg                                        
-1                           4       11.888
STRONG_UPTREND            1276       -0.173
WEAK_UPTREND               717       -0.795
DOWNTREND                 1756        0.327
SIDEWAYS                    60       -1.038
VOLATILITY_EXPANSION       235        2.387
VOLATILITY_CONTRACTION      11       -0.350
POTENTIAL_REVERSAL        1066        0.611

## Verdict on the frozen rule: FAIL  (folds where B beats A: 1/3; B trades pooled: 1805; B - A daily CI lower bound -0.0508%). Development evidence only, non-confirmatory.

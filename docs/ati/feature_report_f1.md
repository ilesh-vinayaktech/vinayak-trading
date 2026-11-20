# ATI baseline feature report (ati-f1)
stocks 1769, sessions 1631, bars before 2025-01-01

              feature      group  lookback  coverage          mean          std        p1           p99
       ema_5_distance      trend         5    0.8779  1.100000e-03 2.950000e-02   -0.0730  9.310000e-02
      ema_10_distance      trend        10    0.8756  2.600000e-03 4.820000e-02   -0.1189  1.624000e-01
      ema_20_distance      trend        20    0.8711  5.800000e-03 7.300000e-02   -0.1796  2.437000e-01
      ema_50_distance      trend        50    0.8573  1.580000e-02 1.210000e-01   -0.2829  3.984000e-01
     ema_100_distance      trend       100    0.8341  3.400000e-02 1.774000e-01   -0.3780  5.882000e-01
     ema_200_distance      trend       200    0.7900  7.300000e-02 2.659000e-01   -0.4968  8.935000e-01
         ema_20_slope      trend        25    0.8955  3.800000e-03 3.690000e-02   -0.0843  1.248000e-01
         ema_50_slope      trend        55    0.8811  3.500000e-03 2.460000e-02   -0.0538  8.080000e-02
        ema_200_slope      trend       205    0.8082  3.700000e-03 1.340000e-02   -0.0240  4.510000e-02
      sma_20_distance      trend        20    0.8373  7.800000e-03 8.520000e-02   -0.1987  2.903000e-01
      sma_50_distance      trend        50    0.7977  2.040000e-02 1.383000e-01   -0.3099  4.576000e-01
     sma_200_distance      trend       200    0.6671  1.078000e-01 2.948000e-01   -0.4746  1.053700e+00
     ema_20_50_spread      trend        50    0.8842  6.600000e-03 6.260000e-02   -0.1733  1.800000e-01
    ema_50_200_spread      trend       200    0.8113  4.050000e-02 1.684000e-01   -0.3957  4.955000e-01
ema_bullish_alignment      trend       200    0.6671  3.182000e-01 4.658000e-01    0.0000  1.000000e+00
ema_bearish_alignment      trend       200    0.6671  1.665000e-01 3.725000e-01    0.0000  1.000000e+00
                rsi_7   momentum         8    0.8569  5.017860e+01 1.765000e+01   11.7791  9.118800e+01
               rsi_14   momentum        15    0.8448  5.066790e+01 1.297180e+01   20.2714  8.263620e+01
               rsi_21   momentum        22    0.8344  5.083360e+01 1.092040e+01   24.2460  7.805370e+01
            macd_line   momentum        26    0.8683  3.000000e-04 4.110000e-02   -0.1321  9.330000e-02
       macd_histogram   momentum        35    0.8642  0.000000e+00 1.190000e-02   -0.0328  3.260000e-02
               roc_10   momentum        11    0.8662  1.230000e-02 1.127000e-01   -0.2352  4.053000e-01
           momentum_5   momentum         6    0.8701  5.000000e-04 7.390000e-02   -0.2000  2.109000e-01
          momentum_10   momentum        11    0.8662  7.000000e-04 1.075000e-01   -0.3076  2.884000e-01
          momentum_20   momentum        21    0.8590  1.400000e-03 1.563000e-01   -0.4824  3.662000e-01
           stoch_k_14   momentum        14    0.8464  4.657420e+01 2.807350e+01    0.3423  1.000000e+02
        williams_r_14   momentum        14    0.8464 -5.342580e+01 2.807350e+01  -99.6577 -0.000000e+00
            atr_pct_7 volatility         8    0.8756  4.787200e+00 2.069800e+00    1.6469  1.161930e+01
           atr_pct_14 volatility        15    0.8714  4.794700e+00 1.939500e+00    1.7775  1.121500e+01
           atr_pct_21 volatility        22    0.8671  4.799100e+00 1.897600e+00    1.8338  1.108630e+01
          bb_width_20 volatility        20    0.8373  2.023000e-01 1.481000e-01    0.0412  7.851000e-01
       bb_position_20 volatility        20    0.8373  5.089000e-01 3.275000e-01   -0.1407  1.240900e+00
          hist_vol_20 volatility        21    0.8569  2.800000e-02 1.370000e-02    0.0084  7.250000e-02
   vol_percentile_252 volatility       273    0.7217  4.972000e-01 3.017000e-01    0.0040  1.000000e+00
        vol_expansion volatility        35    0.8849  2.502279e+04 8.673564e+06    0.5910  2.154800e+00
      vol_contraction volatility        74    0.8641  7.882000e-01 1.582000e-01    0.3736  1.000000e+00
         volume_sma_5     volume         5    0.8634  2.193907e+06 1.599943e+07  716.0000  3.730735e+07
        volume_sma_10     volume        10    0.8532  2.209390e+06 1.520937e+07  929.8970  3.756220e+07
        volume_sma_20     volume        20    0.8373  2.231584e+06 1.455789e+07 1175.7680  3.814712e+07
      relative_volume     volume        20    0.8373  1.048700e+00 1.203000e+00    0.0766  6.399400e+00
  volume_acceleration     volume        20    0.8373  1.013700e+00 5.614000e-01    0.1817  2.952600e+00
         obv_slope_20     volume        21    0.8358  1.029000e-01 3.301000e-01   -0.6570  7.788000e-01
               cmf_20     volume        20    0.7744 -7.860000e-02 1.983000e-01   -0.5077  4.161000e-01
 volume_price_corr_20     volume        21    0.8358  4.466000e-01 2.992000e-01   -0.3122  9.326000e-01
 distance_to_20d_high    channel        20    0.8373 -1.010000e-01 7.580000e-02   -0.3663  0.000000e+00
 distance_to_55d_high    channel        55    0.7916 -1.535000e-01 1.101000e-01   -0.5211 -1.500000e-03
  distance_to_20d_low    channel        20    0.8373  1.278000e-01 1.412000e-01    0.0022  6.710000e-01
    breakout_distance    channel        21    0.8358 -9.980000e-02 8.160000e-02   -0.3735  4.980000e-02
     channel_width_20    channel        20    0.8373  2.250000e-01 1.338000e-01    0.0631  6.920000e-01
  channel_position_55    channel        55    0.7916  4.838000e-01 2.798000e-01    0.0132  9.956000e-01
  keltner_position_20    channel        21    0.8693 -2.320284e+11 2.779701e+14   -1.5547  2.084400e+00
    compression_score    channel        79    0.7970  1.097700e+00 5.793000e-01    0.3950  3.130800e+00
   st_7_1_5_direction supertrend         8    0.8756 -5.330000e-02 9.986000e-01   -1.0000  1.000000e+00
    st_7_1_5_distance supertrend         8    0.8756 -8.800000e-03 6.910000e-02   -0.1678  1.350000e-01
        st_7_1_5_flip supertrend         9    0.8690  6.110000e-02 2.395000e-01    0.0000  1.000000e+00
  st_7_1_5_signal_age supertrend         9    0.8752  1.390360e+01 1.388300e+01    0.0000  6.000000e+01
   st_7_2_0_direction supertrend         8    0.8756 -2.200000e-03 1.000000e+00   -1.0000  1.000000e+00
    st_7_2_0_distance supertrend         8    0.8756 -7.300000e-03 8.780000e-02   -0.2128  1.661000e-01
        st_7_2_0_flip supertrend         9    0.8690  4.220000e-02 2.011000e-01    0.0000  1.000000e+00
  st_7_2_0_signal_age supertrend         9    0.8752  1.946680e+01 1.734340e+01    0.0000  6.000000e+01
   st_7_2_5_direction supertrend         8    0.8756  5.220000e-02 9.986000e-01   -1.0000  1.000000e+00
    st_7_2_5_distance supertrend         8    0.8756 -3.500000e-03 1.066000e-01   -0.2581  1.975000e-01
        st_7_2_5_flip supertrend         9    0.8690  3.090000e-02 1.730000e-01    0.0000  1.000000e+00
  st_7_2_5_signal_age supertrend         9    0.8752  2.501290e+01 1.981070e+01    0.0000  6.000000e+01
   st_7_3_0_direction supertrend         8    0.8756  1.042000e-01 9.946000e-01   -1.0000  1.000000e+00
    st_7_3_0_distance supertrend         8    0.8756  1.900000e-03 1.252000e-01   -0.3036  2.303000e-01
        st_7_3_0_flip supertrend         9    0.8690  2.370000e-02 1.522000e-01    0.0000  1.000000e+00
  st_7_3_0_signal_age supertrend         9    0.8752  2.989690e+01 2.114950e+01    0.0000  6.000000e+01
   st_7_3_5_direction supertrend         8    0.8756  1.501000e-01 9.887000e-01   -1.0000  1.000000e+00
    st_7_3_5_distance supertrend         8    0.8756  8.600000e-03 1.436000e-01   -0.3489  2.632000e-01
        st_7_3_5_flip supertrend         9    0.8690  1.890000e-02 1.361000e-01    0.0000  1.000000e+00
  st_7_3_5_signal_age supertrend         9    0.8752  3.417990e+01 2.170900e+01    0.0000  6.000000e+01
   st_7_4_0_direction supertrend         8    0.8756  1.939000e-01 9.810000e-01   -1.0000  1.000000e+00
    st_7_4_0_distance supertrend         8    0.8756  1.650000e-02 1.617000e-01   -0.3943  2.966000e-01
        st_7_4_0_flip supertrend         9    0.8690  1.530000e-02 1.226000e-01    0.0000  1.000000e+00
  st_7_4_0_signal_age supertrend         9    0.8752  3.794140e+01 2.169130e+01    0.0000  6.000000e+01
  st_10_1_5_direction supertrend        11    0.8738 -7.580000e-02 9.971000e-01   -1.0000  1.000000e+00
   st_10_1_5_distance supertrend        11    0.8738 -1.090000e-02 6.850000e-02   -0.1656  1.308000e-01
       st_10_1_5_flip supertrend        12    0.8672  6.160000e-02 2.405000e-01    0.0000  1.000000e+00
 st_10_1_5_signal_age supertrend        12    0.8734  1.386460e+01 1.385380e+01    0.0000  6.000000e+01
  st_10_2_0_direction supertrend        11    0.8738 -3.240000e-02 9.995000e-01   -1.0000  1.000000e+00
   st_10_2_0_distance supertrend        11    0.8738 -1.090000e-02 8.700000e-02   -0.2111  1.593000e-01
       st_10_2_0_flip supertrend        12    0.8672  4.270000e-02 2.023000e-01    0.0000  1.000000e+00
 st_10_2_0_signal_age supertrend        12    0.8734  1.935080e+01 1.727960e+01    0.0000  6.000000e+01
  st_10_2_5_direction supertrend        11    0.8738  1.450000e-02 9.999000e-01   -1.0000  1.000000e+00
   st_10_2_5_distance supertrend        11    0.8738 -9.000000e-03 1.058000e-01   -0.2577  1.879000e-01
       st_10_2_5_flip supertrend        12    0.8672  3.130000e-02 1.740000e-01    0.0000  1.000000e+00
 st_10_2_5_signal_age supertrend        12    0.8734  2.481220e+01 1.971600e+01    0.0000  6.000000e+01
  st_10_3_0_direction supertrend        11    0.8738  6.310000e-02 9.980000e-01   -1.0000  1.000000e+00
   st_10_3_0_distance supertrend        11    0.8738 -5.100000e-03 1.246000e-01   -0.3045  2.177000e-01
       st_10_3_0_flip supertrend        12    0.8672  2.400000e-02 1.530000e-01    0.0000  1.000000e+00
 st_10_3_0_signal_age supertrend        12    0.8734  2.968830e+01 2.107890e+01    0.0000  6.000000e+01
  st_10_3_5_direction supertrend        11    0.8738  1.099000e-01 9.939000e-01   -1.0000  1.000000e+00
   st_10_3_5_distance supertrend        11    0.8738  3.000000e-04 1.432000e-01   -0.3510  2.484000e-01
       st_10_3_5_flip supertrend        12    0.8672  1.900000e-02 1.364000e-01    0.0000  1.000000e+00
 st_10_3_5_signal_age supertrend        12    0.8734  3.403430e+01 2.167570e+01    0.0000  6.000000e+01
  st_10_4_0_direction supertrend        11    0.8738  1.538000e-01 9.881000e-01   -1.0000  1.000000e+00
   st_10_4_0_distance supertrend        11    0.8738  7.200000e-03 1.615000e-01   -0.3974  2.796000e-01
       st_10_4_0_flip supertrend        12    0.8672  1.530000e-02 1.226000e-01    0.0000  1.000000e+00
 st_10_4_0_signal_age supertrend        12    0.8734  3.784090e+01 2.166070e+01    0.0000  6.000000e+01
  st_14_1_5_direction supertrend        15    0.8714 -9.040000e-02 9.959000e-01   -1.0000  1.000000e+00
   st_14_1_5_distance supertrend        15    0.8714 -1.210000e-02 6.800000e-02   -0.1633  1.283000e-01
       st_14_1_5_flip supertrend        16    0.8648  6.220000e-02 2.415000e-01    0.0000  1.000000e+00
 st_14_1_5_signal_age supertrend        16    0.8709  1.388140e+01 1.393380e+01    0.0000  6.000000e+01
  st_14_2_0_direction supertrend        15    0.8714 -5.550000e-02 9.985000e-01   -1.0000  1.000000e+00
   st_14_2_0_distance supertrend        15    0.8714 -1.350000e-02 8.640000e-02   -0.2092  1.552000e-01
       st_14_2_0_flip supertrend        16    0.8648  4.330000e-02 2.035000e-01    0.0000  1.000000e+00
 st_14_2_0_signal_age supertrend        16    0.8709  1.926570e+01 1.727910e+01    0.0000  6.000000e+01
  st_14_2_5_direction supertrend        15    0.8714 -1.590000e-02 9.999000e-01   -1.0000  1.000000e+00
   st_14_2_5_distance supertrend        15    0.8714 -1.320000e-02 1.051000e-01   -0.2561  1.823000e-01
       st_14_2_5_flip supertrend        16    0.8648  3.170000e-02 1.751000e-01    0.0000  1.000000e+00
 st_14_2_5_signal_age supertrend        16    0.8709  2.469390e+01 1.969890e+01    0.0000  6.000000e+01
  st_14_3_0_direction supertrend        15    0.8714  2.830000e-02 9.996000e-01   -1.0000  1.000000e+00
   st_14_3_0_distance supertrend        15    0.8714 -1.090000e-02 1.239000e-01   -0.3038  2.097000e-01
       st_14_3_0_flip supertrend        16    0.8648  2.430000e-02 1.539000e-01    0.0000  1.000000e+00
 st_14_3_0_signal_age supertrend        16    0.8709  2.951750e+01 2.104550e+01    0.0000  6.000000e+01
  st_14_3_5_direction supertrend        15    0.8714  7.090000e-02 9.975000e-01   -1.0000  1.000000e+00
   st_14_3_5_distance supertrend        15    0.8714 -7.300000e-03 1.427000e-01   -0.3510  2.382000e-01
       st_14_3_5_flip supertrend        16    0.8648  1.920000e-02 1.373000e-01    0.0000  1.000000e+00
 st_14_3_5_signal_age supertrend        16    0.8709  3.381470e+01 2.164800e+01    0.0000  6.000000e+01
  st_14_4_0_direction supertrend        15    0.8714  1.106000e-01 9.939000e-01   -1.0000  1.000000e+00
   st_14_4_0_distance supertrend        15    0.8714 -2.200000e-03 1.614000e-01   -0.3983  2.678000e-01
       st_14_4_0_flip supertrend        16    0.8648  1.550000e-02 1.233000e-01    0.0000  1.000000e+00
 st_14_4_0_signal_age supertrend        16    0.8709  3.760440e+01 2.165640e+01    0.0000  6.000000e+01
  st_20_1_5_direction supertrend        21    0.8677 -9.640000e-02 9.953000e-01   -1.0000  1.000000e+00
   st_20_1_5_distance supertrend        21    0.8677 -1.280000e-02 6.780000e-02   -0.1622  1.271000e-01
       st_20_1_5_flip supertrend        22    0.8613  6.260000e-02 2.423000e-01    0.0000  1.000000e+00
 st_20_1_5_signal_age supertrend        22    0.8672  1.408820e+01 1.430050e+01    0.0000  6.000000e+01
  st_20_2_0_direction supertrend        21    0.8677 -6.920000e-02 9.976000e-01   -1.0000  1.000000e+00
   st_20_2_0_distance supertrend        21    0.8677 -1.500000e-02 8.610000e-02   -0.2078  1.536000e-01
       st_20_2_0_flip supertrend        22    0.8613  4.360000e-02 2.042000e-01    0.0000  1.000000e+00
 st_20_2_0_signal_age supertrend        22    0.8672  1.944240e+01 1.751630e+01    0.0000  6.000000e+01
  st_20_2_5_direction supertrend        21    0.8677 -3.720000e-02 9.993000e-01   -1.0000  1.000000e+00
   st_20_2_5_distance supertrend        21    0.8677 -1.610000e-02 1.047000e-01   -0.2552  1.797000e-01
       st_20_2_5_flip supertrend        22    0.8613  3.200000e-02 1.761000e-01    0.0000  1.000000e+00
 st_20_2_5_signal_age supertrend        22    0.8672  2.470640e+01 1.977340e+01    0.0000  6.000000e+01
  st_20_3_0_direction supertrend        21    0.8677 -2.000000e-03 1.000000e+00   -1.0000  1.000000e+00
   st_20_3_0_distance supertrend        21    0.8677 -1.570000e-02 1.236000e-01   -0.3031  2.062000e-01
       st_20_3_0_flip supertrend        22    0.8613  2.460000e-02 1.548000e-01    0.0000  1.000000e+00
 st_20_3_0_signal_age supertrend        22    0.8672  2.945010e+01 2.106640e+01    0.0000  6.000000e+01
  st_20_3_5_direction supertrend        21    0.8677  3.230000e-02 9.995000e-01   -1.0000  1.000000e+00
   st_20_3_5_distance supertrend        21    0.8677 -1.400000e-02 1.424000e-01   -0.3511  2.334000e-01
       st_20_3_5_flip supertrend        22    0.8613  1.940000e-02 1.381000e-01    0.0000  1.000000e+00
 st_20_3_5_signal_age supertrend        22    0.8672  3.364200e+01 2.163630e+01    0.0000  6.000000e+01
  st_20_4_0_direction supertrend        21    0.8677  6.530000e-02 9.979000e-01   -1.0000  1.000000e+00
   st_20_4_0_distance supertrend        21    0.8677 -1.110000e-02 1.613000e-01   -0.3994  2.613000e-01
       st_20_4_0_flip supertrend        22    0.8613  1.570000e-02 1.243000e-01    0.0000  1.000000e+00
 st_20_4_0_signal_age supertrend        22    0.8672  3.734390e+01 2.166830e+01    0.0000  6.000000e+01
  st_21_1_5_direction supertrend        22    0.8671 -9.840000e-02 9.952000e-01   -1.0000  1.000000e+00
   st_21_1_5_distance supertrend        22    0.8671 -1.290000e-02 6.770000e-02   -0.1622  1.269000e-01
       st_21_1_5_flip supertrend        23    0.8607  6.270000e-02 2.425000e-01    0.0000  1.000000e+00
 st_21_1_5_signal_age supertrend        23    0.8666  1.407250e+01 1.429010e+01    0.0000  6.000000e+01
  st_21_2_0_direction supertrend        22    0.8671 -7.150000e-02 9.974000e-01   -1.0000  1.000000e+00
   st_21_2_0_distance supertrend        22    0.8671 -1.520000e-02 8.600000e-02   -0.2077  1.533000e-01
       st_21_2_0_flip supertrend        23    0.8607  4.370000e-02 2.044000e-01    0.0000  1.000000e+00
 st_21_2_0_signal_age supertrend        23    0.8666  1.943600e+01 1.752290e+01    0.0000  6.000000e+01
  st_21_2_5_direction supertrend        22    0.8671 -4.010000e-02 9.992000e-01   -1.0000  1.000000e+00
   st_21_2_5_distance supertrend        22    0.8671 -1.640000e-02 1.047000e-01   -0.2551  1.793000e-01
       st_21_2_5_flip supertrend        23    0.8607  3.210000e-02 1.762000e-01    0.0000  1.000000e+00
 st_21_2_5_signal_age supertrend        23    0.8666  2.468310e+01 1.976650e+01    0.0000  6.000000e+01
  st_21_3_0_direction supertrend        22    0.8671 -6.800000e-03 1.000000e+00   -1.0000  1.000000e+00
   st_21_3_0_distance supertrend        22    0.8671 -1.640000e-02 1.235000e-01   -0.3030  2.057000e-01
       st_21_3_0_flip supertrend        23    0.8607  2.460000e-02 1.550000e-01    0.0000  1.000000e+00
 st_21_3_0_signal_age supertrend        23    0.8666  2.941000e+01 2.105900e+01    0.0000  6.000000e+01
  st_21_3_5_direction supertrend        22    0.8671  2.640000e-02 9.997000e-01   -1.0000  1.000000e+00
   st_21_3_5_distance supertrend        22    0.8671 -1.500000e-02 1.423000e-01   -0.3515  2.325000e-01
       st_21_3_5_flip supertrend        23    0.8607  1.950000e-02 1.383000e-01    0.0000  1.000000e+00
 st_21_3_5_signal_age supertrend        23    0.8666  3.358820e+01 2.163500e+01    0.0000  6.000000e+01
  st_21_4_0_direction supertrend        22    0.8671  5.980000e-02 9.982000e-01   -1.0000  1.000000e+00
   st_21_4_0_distance supertrend        22    0.8671 -1.230000e-02 1.612000e-01   -0.3997  2.606000e-01
       st_21_4_0_flip supertrend        23    0.8607  1.580000e-02 1.246000e-01    0.0000  1.000000e+00
 st_21_4_0_signal_age supertrend        23    0.8666  3.728320e+01 2.167300e+01    0.0000  6.000000e+01

## Pairs with |Spearman| >= 0.9 (60; SuperTrend grid represented by ATR 14 x3.0)

- stoch_k_14 ~ williams_r_14: +1.00
- roc_10 ~ momentum_10: +1.00
- atr_pct_14 ~ atr_pct_21: +0.99
- distance_to_20d_high ~ breakout_distance: +0.98
- ema_200_distance ~ ema_200_slope: +0.98
- volume_sma_5 ~ volume_sma_10: +0.98
- volume_sma_10 ~ volume_sma_20: +0.98
- ema_20_distance ~ keltner_position_20: +0.98
- rsi_14 ~ keltner_position_20: +0.98
- ema_200_distance ~ sma_200_distance: +0.98
- ema_50_distance ~ sma_50_distance: +0.97
- ema_20_distance ~ sma_20_distance: +0.97
- rsi_14 ~ rsi_21: +0.97
- ema_50_slope ~ macd_line: +0.97
- ema_50_distance ~ rsi_21: +0.97
- ema_200_slope ~ sma_200_distance: +0.97
- rsi_7 ~ keltner_position_20: +0.97
- atr_pct_7 ~ atr_pct_14: +0.96
- volume_sma_5 ~ volume_sma_20: +0.96
- ema_20_distance ~ rsi_14: +0.96
- rsi_7 ~ bb_position_20: +0.96
- ema_10_distance ~ rsi_7: +0.96
- sma_20_distance ~ keltner_position_20: +0.96
- sma_50_distance ~ macd_line: +0.95
- sma_50_distance ~ rsi_21: +0.95
- bb_position_20 ~ keltner_position_20: +0.95
- sma_20_distance ~ bb_position_20: +0.95
- ema_20_distance ~ rsi_7: +0.95
- ema_50_distance ~ ema_50_slope: +0.94
- ema_50_slope ~ sma_50_distance: +0.94
- sma_20_distance ~ rsi_7: +0.93
- ema_20_distance ~ bb_position_20: +0.93
- rsi_21 ~ channel_position_55: +0.93
- rsi_7 ~ rsi_14: +0.93
- ema_5_distance ~ ema_10_distance: +0.93
- rsi_7 ~ williams_r_14: +0.93
- rsi_7 ~ stoch_k_14: +0.93
- ema_10_distance ~ ema_20_distance: +0.93
- ema_50_distance ~ macd_line: +0.92
- ema_100_distance ~ ema_200_distance: +0.92
- sma_20_distance ~ rsi_14: +0.92
- ema_50_distance ~ ema_100_distance: +0.92
- ema_100_distance ~ ema_20_50_spread: +0.92
- ema_50_distance ~ rsi_14: +0.92
- rsi_21 ~ keltner_position_20: +0.92
- ema_10_distance ~ keltner_position_20: +0.92
- ema_100_distance ~ ema_50_slope: +0.91
- rsi_14 ~ bb_position_20: +0.91
- ema_10_distance ~ bb_position_20: +0.91
- atr_pct_7 ~ atr_pct_21: +0.91
- ema_200_slope ~ ema_50_200_spread: +0.91
- sma_50_distance ~ channel_position_55: +0.91
- ema_10_distance ~ sma_20_distance: +0.91
- ema_50_distance ~ channel_position_55: +0.91
- ema_100_distance ~ sma_200_distance: +0.91
- ema_20_distance ~ rsi_21: +0.90
- williams_r_14 ~ bb_position_20: +0.90
- stoch_k_14 ~ bb_position_20: +0.90
- sma_50_distance ~ rsi_14: +0.90
- bb_width_20 ~ channel_width_20: +0.90

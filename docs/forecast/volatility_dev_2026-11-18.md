# Volatility forecast: development-period evaluation (sessions to 2024-12-31; the 2025 holdout is not read)

Made 2026-11-18. 2224 sessions (2016-01-06 to 2024-12-31), forecast before the open from yesterday's ranges, India VIX and the US overnight. Walk-forward: refitted every 21 sessions on earlier sessions only, first 500 used to fit. Ridge strength 10.0, inputs and baselines fixed in advance. Errors are in % points of the index.

## next-session high-low range (% of open)

1724 sessions scored (average actual 1.137).

| Forecast | MAE | RMSE | Bias (forecast minus actual) | Direction of the change right |
|---|---|---|---|---|
| Model | 0.4035 | 0.6952 | -0.0118 | 66.6% |
| Yesterday's value | 0.4916 | 0.8444 | -0.0003 | 51.3% |
| Average of the last 5 sessions | 0.4384 | 0.7401 | -0.0006 | 65.6% |
| Average of the last 22 sessions | 0.4644 | 0.8120 | -0.0019 | 66.5% |
| India VIX scaled | 0.4424 | 0.7380 | +0.0143 | 65.8% |

- MAE gap against **Yesterday's value** (baseline minus model): +0.0881 (95% +0.0676 to +0.1119), so the model is **better than** it.
- MAE gap against **Average of the last 5 sessions** (baseline minus model): +0.0349 (95% +0.0199 to +0.0513), so the model is **better than** it.
- MAE gap against **Average of the last 22 sessions** (baseline minus model): +0.0610 (95% +0.0341 to +0.0966), so the model is **better than** it.
- MAE gap against **India VIX scaled** (baseline minus model): +0.0389 (95% +0.0285 to +0.0522), so the model is **better than** it.

Which inputs matter (the model refitted without a group; MAE on the same sessions):

| Inputs | MAE |
|---|---|
| all inputs | 0.4035 |
| without India VIX | 0.4132 |
| without the US overnight | 0.4085 |
| without the recent ranges and moves | 0.4355 |

By India VIX regime (yesterday's close; thirds of the whole period) and by year, model against the best simple baseline (average of the last 22 sessions):

| Segment | Sessions | Model MAE | 22-session average MAE |
|---|---|---|---|
| VIX low | 516 | 0.2671 | 0.3071 |
| VIX middle | 544 | 0.3819 | 0.4244 |
| VIX high | 664 | 0.5271 | 0.6195 |
| 2018 | 238 | 0.3477 | 0.3872 |
| 2019 | 244 | 0.3653 | 0.3804 |
| 2020 | 251 | 0.6204 | 0.7939 |
| 2021 | 248 | 0.4085 | 0.4435 |
| 2022 | 248 | 0.3958 | 0.4400 |
| 2023 | 246 | 0.2451 | 0.2877 |
| 2024 | 249 | 0.4345 | 0.5082 |

Calibration of the level (sessions grouped by the size of the forecast):

| Forecast group | Sessions | Average forecast | Average actual |
|---|---|---|---|
| fifth 1 (smallest to largest) | 345 | 0.714 | 0.715 |
| fifth 2 (smallest to largest) | 345 | 0.872 | 0.904 |
| fifth 3 (smallest to largest) | 344 | 1.021 | 1.026 |
| fifth 4 (smallest to largest) | 345 | 1.202 | 1.205 |
| fifth 5 (smallest to largest) | 345 | 1.818 | 1.835 |

## next-session absolute close-to-close move (%)

1724 sessions scored (average actual 0.733).

| Forecast | MAE | RMSE | Bias (forecast minus actual) | Direction of the change right |
|---|---|---|---|---|
| Model | 0.4538 | 0.6945 | +0.0232 | 73.4% |
| Yesterday's value | 0.6112 | 0.9605 | +0.0000 | 50.5% |
| Average of the last 5 sessions | 0.4968 | 0.7657 | +0.0003 | 71.6% |
| Average of the last 22 sessions | 0.4816 | 0.7636 | -0.0002 | 71.9% |
| India VIX scaled | 0.4685 | 0.7246 | +0.0243 | 71.5% |

- MAE gap against **Yesterday's value** (baseline minus model): +0.1574 (95% +0.1229 to +0.2047), so the model is **better than** it.
- MAE gap against **Average of the last 5 sessions** (baseline minus model): +0.0430 (95% +0.0279 to +0.0596), so the model is **better than** it.
- MAE gap against **Average of the last 22 sessions** (baseline minus model): +0.0278 (95% +0.0087 to +0.0492), so the model is **better than** it.
- MAE gap against **India VIX scaled** (baseline minus model): +0.0147 (95% +0.0064 to +0.0244), so the model is **better than** it.

Which inputs matter (the model refitted without a group; MAE on the same sessions):

| Inputs | MAE |
|---|---|
| all inputs | 0.4538 |
| without India VIX | 0.4544 |
| without the US overnight | 0.4539 |
| without the recent ranges and moves | 0.4634 |

By India VIX regime (yesterday's close; thirds of the whole period) and by year, model against the best simple baseline (average of the last 22 sessions):

| Segment | Sessions | Model MAE | 22-session average MAE |
|---|---|---|---|
| VIX low | 516 | 0.3150 | 0.3369 |
| VIX middle | 544 | 0.3995 | 0.4131 |
| VIX high | 664 | 0.6060 | 0.6502 |
| 2018 | 238 | 0.3871 | 0.4052 |
| 2019 | 244 | 0.4038 | 0.4057 |
| 2020 | 251 | 0.6958 | 0.7842 |
| 2021 | 248 | 0.4440 | 0.4442 |
| 2022 | 248 | 0.4946 | 0.5392 |
| 2023 | 246 | 0.3030 | 0.2981 |
| 2024 | 249 | 0.4404 | 0.4852 |

Calibration of the level (sessions grouped by the size of the forecast):

| Forecast group | Sessions | Average forecast | Average actual |
|---|---|---|---|
| fifth 1 (smallest to largest) | 345 | 0.437 | 0.461 |
| fifth 2 (smallest to largest) | 345 | 0.559 | 0.554 |
| fifth 3 (smallest to largest) | 344 | 0.669 | 0.674 |
| fifth 4 (smallest to largest) | 345 | 0.801 | 0.732 |
| fifth 5 (smallest to largest) | 345 | 1.315 | 1.244 |


## Conclusions (written by hand after the figures; development data only, 2016 to 2024-12-31)

1. **The volatility forecast works, unlike the direction forecast.** For the next session's high-low range the model's mean absolute error is 0.404 (percent of the open), against 0.438 for the best
   simple baseline (the last five sessions' average) and 0.442 for India VIX scaled; all four gaps have 95% intervals above zero. It is better than the 22-session average in every VIX regime and in every year
   from 2018 to 2024, and its level is calibrated across forecast fifths (smallest group: forecast 0.71, actual 0.72; largest: 1.82 against 1.84). Direction-of-change accuracy is 67%, but the simple averages
   are 66%, so that figure does not separate them.
2. **The secondary target (absolute close-to-close move) is better than every baseline too, by less:** MAE 0.454 against 0.469 for India VIX scaled (gap +0.015, interval +0.006 to +0.024), and it is no better than
   the 22-session average in 2019, 2021 and 2023. The range is the primary target for a reason.
3. **What carries it:** the recent ranges and moves (MAE 0.436 without them against 0.404 with all inputs), then India VIX (0.413 without it), then the US overnight (0.409 without it): the US matters much less for
   the size of a move than for its direction.
4. **Limits:** development data only; the 2025 holdout has not been read. Not shown on the page, not in the job, not a registered forward test. Realised volatility from intraday returns (the spec's secondary target)
   was not built: the stored one-minute history is too short for a 2016-2024 evaluation.

# Forecast evaluation: market, 1-day, walk-forward

> **Disclosure (added in review).** This report covers 2020-02-11 to 2026-11-16 and therefore **includes the accessed 2025-2026 period** (the global holdout). Every figure here, including the
> intervals, the calibration table and the by-year table, mixes development and accessed days. It is a description of the system as built, not confirmation of anything; see
> `diagnosis_2026-11-18.md` and `calibration_abstain_2026-11-18.md` for development-only figures.

Made 2026-11-18. 1678 days, 2020-02-11 to 2026-11-16; every model is scored on exactly these days. 948 rose, 730 did not.

Intervals are 95%, from a moving-block bootstrap (blocks of 20 days), because neighbouring days are not independent.

## Scores

| Model | Accuracy | Brier | Brier skill vs usual tendency | Log loss | AUC | Precision | Recall |
|---|---|---|---|---|---|---|---|
| Morning model (with the US close) | 58.9% | 0.2392 | +0.0322 | 0.6727 | 0.605 | 0.611 | 0.750 |
| Usual tendency (share of up days known so far) | 56.3% | 0.2471 | +0.0000 | 0.6946 | 0.500 | 0.567 | 0.960 |
| Yesterday's direction | 56.1% | 0.2453 | +0.0073 | 0.6909 | 0.546 | 0.575 | 0.857 |
| 21-day momentum | 55.8% | 0.2467 | +0.0019 | 0.6936 | 0.525 | 0.566 | 0.927 |
| Night model (no overnight inputs) | 54.4% | 0.2494 | -0.0091 | 0.6924 | 0.535 | 0.575 | 0.738 |

Morning model confusion matrix (called up / called down against rose / did not): TP 711, FP 452, FN 237, TN 278.

## Is the morning model better than the references?

- Against **Usual tendency (share of up days known so far)**: Brier gap +0.0079 (95% +0.0015 to +0.0141), so the morning model is **better** it.
- Against **Yesterday's direction**: Brier gap +0.0061 (95% +0.0003 to +0.0118), so the morning model is **better** it.
- Against **21-day momentum**: Brier gap +0.0075 (95% +0.0015 to +0.0133), so the morning model is **better** it.
- Against **Night model (no overnight inputs)**: Brier gap +0.0102 (95% +0.0065 to +0.0144), so the morning model is **better** it.

Morning accuracy 58.9% (95% 56.1% to 61.4%); Brier skill vs the usual tendency +0.0322 (95% +0.0062 to +0.0562).

## Calibration (morning model)

| Said | Days | Average said | Actually rose |
|---|---|---|---|
| 0% to 40% | 210 | 31.9% | 41.0% |
| 40% to 45% | 126 | 42.5% | 46.0% |
| 45% to 50% | 179 | 47.7% | 52.0% |
| 50% to 55% | 266 | 52.5% | 52.6% |
| 55% to 60% | 275 | 57.5% | 59.3% |
| 60% to 65% | 276 | 62.4% | 63.8% |
| 65% to 70% | 201 | 67.6% | 66.2% |
| 70% to 75% | 98 | 72.0% | 71.4% |
| 75% to 100% | 47 | 80.7% | 61.7% |

## By trend (morning model)

| Segment | Days | Accuracy | Brier skill | Share that rose |
|---|---|---|---|---|
| BEAR | 299 | 59.9% | +0.0780 | 55.5% |
| BULL | 984 | 59.0% | +0.0208 | 57.6% |
| SIDEWAYS | 395 | 58.0% | +0.0237 | 54.4% |

## By volatility (morning model)

| Segment | Days | Accuracy | Brier skill | Share that rose |
|---|---|---|---|---|
| CALM | 589 | 59.1% | +0.0399 | 55.0% |
| NORMAL | 770 | 58.1% | +0.0311 | 56.2% |
| STRESSED | 319 | 60.8% | +0.0202 | 59.9% |

## By market zone (morning model)

| Segment | Days | Accuracy | Brier skill | Share that rose |
|---|---|---|---|---|
| Extreme fear | 213 | 56.3% | -0.0201 | 54.0% |
| Extreme greed | 135 | 60.0% | -0.0184 | 61.5% |
| Fear | 676 | 57.7% | +0.0499 | 53.3% |
| Greed | 654 | 60.9% | +0.0407 | 59.6% |

## By year (morning model)

| Year | Days | Accuracy | Brier skill |
|---|---|---|---|
| 2020 | 222 | 64.4% | +0.0327 |
| 2021 | 248 | 57.3% | +0.0234 |
| 2022 | 248 | 62.1% | +0.1196 |
| 2023 | 246 | 63.8% | +0.0488 |
| 2024 | 249 | 59.4% | -0.0077 |
| 2025 | 249 | 52.2% | -0.0103 |
| 2026 | 216 | 53.2% | +0.0158 |

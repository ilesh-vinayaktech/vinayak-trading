# Why did the morning forecast's edge fade? Development-period diagnosis

Made 2026-11-18. Days 2016-01-06 to 2024-12-31 (2225): **development data only** (the study window ends 2024-12-31; the 2025-01-01 holdout is not read). Descriptive: nothing is fitted or chosen here.

## 1. Does the US still drive the Indian day?

Model-free: the S&P 500's last session against the Nifty 500 that day. `Rule` = call the day up when the S&P rose.

| Year | Days | Corr S&P with open gap | Corr S&P with intraday move | Corr S&P with close-to-close | Beta (close-to-close per 1% S&P) | Rule accuracy | Share of days up |
|---|---|---|---|---|---|---|---|
| 2016 | 244 | +0.32 | +0.03 | +0.22 | +0.26 | 57.4% | 54.9% |
| 2017 | 248 | +0.42 | +0.04 | +0.24 | +0.35 | 57.3% | 60.9% |
| 2018 | 246 | +0.62 | -0.16 | +0.25 | +0.20 | 57.7% | 51.2% |
| 2019 | 245 | +0.15 | -0.08 | -0.01 | -0.01 | 54.7% | 52.2% |
| 2020 | 251 | +0.47 | -0.02 | +0.30 | +0.27 | 64.9% | 62.9% |
| 2021 | 248 | +0.44 | -0.06 | +0.18 | +0.21 | 56.0% | 56.9% |
| 2022 | 248 | +0.69 | -0.05 | +0.42 | +0.30 | 60.1% | 53.2% |
| 2023 | 246 | +0.60 | +0.04 | +0.34 | +0.25 | 57.3% | 58.5% |
| 2024 | 249 | +0.45 | -0.08 | +0.16 | +0.19 | 54.6% | 61.4% |

## 2. Is the gap held or faded during the day?

If the US-driven opening gap is increasingly reversed by the close, the close-to-close day follows the US less even though the opening still does.

| Year | Corr (gap, intraday move) | Gap held by the close (same sign) | Average |gap| % | Average |intraday| % | Gap's share of the day's variance |
|---|---|---|---|---|---|
| 2016 | -0.18 | 66.8% | 0.38 | 0.63 | 39% |
| 2017 | +0.03 | 66.9% | 0.27 | 0.40 | 23% |
| 2018 | -0.19 | 64.6% | 0.36 | 0.59 | 40% |
| 2019 | +0.08 | 64.9% | 0.26 | 0.56 | 16% |
| 2020 | -0.07 | 74.1% | 0.76 | 0.91 | 45% |
| 2021 | +0.03 | 65.7% | 0.43 | 0.60 | 26% |
| 2022 | -0.02 | 68.5% | 0.55 | 0.64 | 44% |
| 2023 | +0.03 | 68.7% | 0.27 | 0.38 | 25% |
| 2024 | -0.02 | 65.5% | 0.34 | 0.54 | 26% |

## 3. Do the inputs behave differently?

| Year | S&P daily std % | Share of |S&P| over 1% | US VIX change std % | Nifty 500 close-to-close std % | India VIX average |
|---|---|---|---|---|---|
| 2016 | 0.83 | 18% | 8.0 | 0.97 | 16.6 |
| 2017 | 0.42 | 3% | 7.1 | 0.61 | 12.6 |
| 2018 | 1.08 | 25% | 11.7 | 0.84 | 15.1 |
| 2019 | 0.76 | 15% | 7.6 | 0.86 | 16.6 |
| 2020 | 2.10 | 42% | 9.5 | 1.85 | 26.8 |
| 2021 | 0.80 | 20% | 9.4 | 0.95 | 18.0 |
| 2022 | 1.51 | 48% | 6.9 | 1.09 | 19.3 |
| 2023 | 0.83 | 26% | 5.5 | 0.61 | 12.4 |
| 2024 | 0.79 | 20% | 9.4 | 0.94 | 14.7 |

## 4. Volatility regimes (India VIX at the previous close; thirds at 13.9 and 17.2, over the whole development period)

| Year | Regime | Days | Corr S&P with close-to-close | Rule accuracy |
|---|---|---|---|---|
| 2016 | middle | 150 | +0.30 | 55.3% |
| 2016 | high | 76 | +0.14 | 63.2% |
| 2017 | low | 200 | +0.24 | 56.5% |
| 2017 | middle | 48 | +0.30 | 60.4% |
| 2018 | low | 103 | +0.25 | 57.3% |
| 2018 | middle | 87 | +0.22 | 55.2% |
| 2018 | high | 56 | +0.31 | 62.5% |
| 2019 | low | 39 | +0.26 | 53.8% |
| 2019 | middle | 148 | +0.02 | 56.1% |
| 2019 | high | 57 | -0.15 | 50.9% |
| 2020 | high | 213 | +0.30 | 65.3% |
| 2021 | low | 46 | +0.32 | 54.3% |
| 2021 | middle | 74 | +0.29 | 55.4% |
| 2021 | high | 128 | +0.13 | 57.0% |
| 2022 | middle | 45 | +0.45 | 57.8% |
| 2022 | high | 186 | +0.41 | 60.8% |
| 2023 | low | 201 | +0.36 | 58.2% |
| 2023 | middle | 43 | +0.31 | 55.8% |
| 2024 | low | 107 | +0.14 | 55.1% |
| 2024 | middle | 120 | +0.16 | 51.7% |

## 5. Calibration of the stored walk-forward probabilities, by year

Slope: 1 is calibrated; below 1 the model is overconfident (its probabilities are too far from 50%). Fitted on the year's own predictions, as a measurement only.

| Year | Days | Average said | Actually rose | Slope | Brier skill vs usual tendency | Accuracy |
|---|---|---|---|---|---|---|
| 2020 | 222 | 52.4% | 63.5% | 0.66 | +0.0327 | 64.4% |
| 2021 | 248 | 54.9% | 56.9% | 0.61 | +0.0234 | 57.3% |
| 2022 | 248 | 53.8% | 53.2% | 1.25 | +0.1196 | 62.1% |
| 2023 | 246 | 56.4% | 58.5% | 1.04 | +0.0488 | 63.8% |
| 2024 | 249 | 56.4% | 61.4% | 0.46 | -0.0077 | 59.4% |

## 6. Is it the relationship or the mix of days? Rule accuracy by the size of the US move

If the relationship decayed, accuracy at a given US move size would fall over time; if only the mix changed, it would not.

| S&P move | 2016-19 | 2020-21 | 2022-23 | 2024 |
|---|---|---|---|---|
| under 0.5% | 52.0% (604 days) | 51.4% (214 days) | 44.6% (186 days) | 44.7% (132 days) |
| 0.5 to 1% | 62.9% (229 days) | 69.0% (129 days) | 62.7% (126 days) | 63.2% (68 days) |
| over 1% | 66.7% (150 days) | 66.0% (156 days) | 70.3% (182 days) | 69.4% (49 days) |
| *Share of days over 1%* | 15% | 31% | 37% | 20% |

Correlation of the S&P with the Nifty 500 close-to-close: 2024 +0.16 against 2020-2023 +0.32 (Fisher z -2.3).

## 7. Brier skill by year with 95% block-bootstrap intervals (stored walk-forward)

| Year | Days | Brier skill | 95% interval |
|---|---|---|---|
| 2020 | 222 | +0.0327 | -0.1080 to +0.1250 |
| 2021 | 248 | +0.0234 | -0.0354 to +0.0715 |
| 2022 | 248 | +0.1196 | +0.0704 to +0.1826 |
| 2023 | 246 | +0.0488 | +0.0094 to +0.0880 |
| 2024 | 249 | -0.0077 | -0.0577 to +0.0381 |

- 2024 minus 2020-2023: -0.0650 (95% -0.1259 to -0.0004)
- 2024 minus 2022-2023: -0.0927 (95% -0.1530 to -0.0291)
- 2024 minus 2020-2021: -0.0354 (95% -0.1020 to +0.0540)

## Conclusions (written by hand after the figures above; re-running the script does not change this section)

Development data only; 2025 onward was not read. Because the earlier evaluation report already printed 2025 and 2026 by year, that period is treated as **accessed** and
cannot serve as confirmatory evidence for any candidate.

1. **The fade within development data is mostly a change in the mix of days, not a decay of the relationship.** At a given size of US move the rule's accuracy is stable
   across periods: over 1%, 66% to 70% in every period (2024: 69%); 0.5 to 1%, 63% to 69% (2024: 63%); under 0.5%, a coin flip or worse in every period (44% to 52%).
   What differs is how many informative days there are: over 1% moves were 31% and 37% of days in 2020-21 and 2022-23 but 20% in 2024 (and 15% in 2016-19); under 0.5% moves
   were 53% of 2024. The correlation falls with them (+0.16 in 2024 against +0.32 in 2020-23, z -2.3), as a correlation does when the driver moves less.
2. **2022-2023 were the unusual years, not 2024.** Brier skill by year: 2020 +0.03, 2021 +0.02, 2022 +0.12, 2023 +0.05, 2024 -0.01. Only 2022 and 2023 have intervals clear of
   zero; 2020, 2021 and 2024 are each indistinguishable from zero and from each other (2024 minus 2020-21: -0.035, interval -0.10 to +0.05). 2024 is significantly below
   2022-23 (-0.093, interval -0.153 to -0.029), but those were the years the US drove Indian markets hardest (S&P daily moves of 2.1% and 1.5%, 42% and 48% of days over 1%).
   The "+0.09 to +0.006" fall is largely a return from an unusually good stretch.
3. **No sign of a structural change in how the day unfolds.** The share of opening gaps held to the close is 65% to 74% every year with no trend, and the gap and the
   intraday move are uncorrelated each year. The gap's share of the day's variance moves with US volatility (16% to 45%), not with time.
4. **Calibration is uneven.** The slope is below 1 (overconfident) in 2020, 2021 and 2024 (0.66, 0.61, 0.46), about 1 in 2022-23 (1.25, 1.04).
5. **Not established either way:** whether the edge continues from 2025. That needs independent forward observations; the accessed holdout cannot give it.

What this does not rule out: a real but small edge that appears only when the US moves a lot. It also means that on days when the S&P moved under 0.5% (about half the
days in a calm year) the call carries almost no information, which the page does not yet say.

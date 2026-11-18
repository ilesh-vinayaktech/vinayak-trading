# Calibration and abstaining: development-period test (days to 2024-12-31; the 2025 holdout is not read)

Made 2026-11-18. The morning model's stored walk-forward predictions, 963 days (2021-02-11 to 2024-12-31), the first 250 used only to fit the calibrator. Two choices fixed in advance: Platt scaling refitted every 21 days on earlier predictions with known outcomes, and no call when the S&P 500 moved under 0.5%.

## 1. Calibration

| | Brier | Brier skill vs usual tendency | Log loss | Accuracy | Calibration slope |
|---|---|---|---|---|---|
| Unchanged | 0.2335 | +0.0538 | 0.6590 | 60.6% | 0.89 |
| Calibrated | 0.2353 | +0.0461 | 0.6633 | 60.7% | 1.05 |

Brier gap (unchanged minus calibrated, positive means calibration helps): -0.00188 (95% -0.00541 to +0.00233).

Calibration table, unchanged against calibrated:

| Said | Days | Said (unchanged) | Rose | Said (calibrated) | Rose |
|---|---|---|---|---|---|
| 0% to 40% | 104 | 32.5% | 34.6% | 35.9% (30 days) | 16.7% |
| 40% to 45% | 67 | 42.5% | 47.8% | 43.1% (45 days) | 42.2% |
| 45% to 50% | 101 | 47.7% | 52.5% | 47.7% (64 days) | 46.9% |
| 50% to 55% | 146 | 52.5% | 53.4% | 52.9% (102 days) | 50.0% |
| 55% to 60% | 160 | 57.5% | 61.9% | 57.6% (175 days) | 55.4% |
| 60% to 65% | 166 | 62.4% | 66.3% | 62.5% (230 days) | 63.5% |
| 65% to 70% | 131 | 67.6% | 64.1% | 67.4% (194 days) | 63.4% |
| 70% to 75% | 67 | 72.1% | 67.2% | 72.1% (107 days) | 67.3% |
| 75% to 100% | 21 | 78.8% | 81.0% | 78.5% (16 days) | 68.8% |

## 2. Abstaining when the S&P moved under 0.5%

Called on 527 of 963 days (55%); no call on 436.

| Days | Count | Accuracy | Brier skill vs usual tendency | Share that rose |
|---|---|---|---|---|
| All days | 963 | 60.6% | +0.0538 | 57.5% |
| Called (S&P moved at least 0.5%) | 527 | 62.4% | +0.0987 | 54.6% |
| No call (S&P moved under 0.5%) | 436 | 58.5% | -0.0019 | 61.0% |

Accuracy on called days 62.4% (95% 58.8% to 66.2%); called minus no-call accuracy +3.9% (95% -2.9% to +9.9%).

Stable over time? (called against no-call days, by period)

| Period | Called days | Accuracy called | No-call days | Accuracy no-call |
|---|---|---|---|---|
| 2020-2021 | 102 | 58.8% | 118 | 55.1% |
| 2022-2023 | 308 | 63.0% | 186 | 62.9% |
| 2024 | 117 | 64.1% | 132 | 55.3% |

## 3. Both together (calibrated probabilities, called days only)

Accuracy 62.2%, Brier skill vs usual tendency +0.0765, on 527 days; the unchanged model on the same days: accuracy 62.4%, Brier skill +0.0987.


## Conclusions (written by hand after the figures; development data only)

1. **Calibration: no case for it.** Platt scaling made the Brier score slightly worse (gap -0.0019, interval -0.0054 to +0.0023, so no better and possibly worse), and the unchanged model's calibration slope in this
   period is already 0.89. The overconfidence seen earlier in the top probability bucket came from the whole-sample figures, which include the accessed 2025-2026 period; in development data that bucket was
   well calibrated (said 79%, rose 81%, 21 days). Not pursued.
2. **Abstaining is not an accuracy trick; it is a statement of where the model has any skill.** On days the S&P moved under 0.5% (45% of days) the model's accuracy is 58.5% only because the market rose on 61% of
   those days; its Brier skill over the usual tendency there is -0.002, i.e. none. On days the S&P moved 0.5% or more its Brier skill is +0.099. The accuracy gap (+3.9 points) is not significant (interval
   -2.9 to +9.9), but the skill gap is large, and the called-day accuracy was higher than the no-call accuracy in each of the three periods (58.8 against 55.1, 63.0 against 62.9, 64.1 against 55.3).
3. **What to do with it:** say it on the page (a note, not a model change): when the US moved little overnight the call is only the usual tendency. Not a promotable forecast candidate, and not a reason to
   withhold the forecast. Whether called-day skill persists forward is untested.

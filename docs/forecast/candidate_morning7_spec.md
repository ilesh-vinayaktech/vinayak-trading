# Candidate `morning7`: frozen specification and promotion rule

**Status: FROZEN 2026-11-18 (owner decision on section 9 received).** Nothing below may change. The freeze time and the SHA-256 of this file and of the code that implements it are in
`candidate_morning7_freeze.json`; a prediction counts only if it was made after that time. The first counted run is the morning of 2026-11-19, 08:50 IST. Nothing from 2025-01-01 on (the global holdout, already
accessed) was used to choose this candidate's design or will be used to confirm it; it was chosen on development-period results (to 2024-12-31) after seeing them, so it is a
**research candidate that has earned a test, not a replacement**. Production stays `logit-v2-morning` (18 features).

## 1. What is predicted
- Subject: the Nifty 500 (`MARKET`). Horizon: 1 trading day. Target: the next session's close is above the close of the day the call is made after (`outcome_up`).
- Prediction time: 08:50 IST on the morning of the session it forecasts (job `forecast-morning`, command `scripts/build_predictions.py --product morning7`).
- Not in scope: the 5-day horizon, sectors, GIFT Nifty (not an input to either model).

## 2. Information cutoff (identical for both models)
Both models are produced by the same job run, from the same stored data, minutes apart. Indian data through the close of the previous session (breadth and the score are built
at 21:45 IST); the last US sessions dated before the session being forecast (S&P 500, Nasdaq Composite, US VIX closes loaded in that run from Yahoo Finance, available about 02:30 IST).
The candidate's seven inputs are a strict subset of production's eighteen; it sees nothing production does not.

## 3. Features (exactly seven), version `logit-v2-morning7`
| Name | Definition |
|---|---|
| `ret_1d`, `ret_5d`, `ret_21d` | Nifty 500 close on the last session against the close 1, 5 and 21 sessions earlier, in % |
| `adv_share` | stocks that rose as a % of stocks that rose or fell on the last session (the liquid universe of that day) |
| `us_sp`, `us_nq`, `us_vix` | % change of the S&P 500, Nasdaq Composite and ^VIX in the last US session dated before the forecast session, against the session before it |

## 4. Missing values
A missing figure stays missing and is filled with the training rows' average inside the model (it neither pushes nor is named as a reason). If any of the three US
figures is missing, no morning prediction is made for that day by either model, so no pair exists and the day is not counted. Missing predictions are counted in the report.

## 5. Model and training (identical procedure for both models; only the feature set differs)
- L2 logistic regression, `C = 0.05`, `max_iter = 500`, lbfgs; features standardised by the training rows' mean and standard deviation (floor on a constant column).
- No probability calibration.
- Refitted from scratch at every run on every market row whose outcome is already known at that run (history from the start of the stored series, at most the last 2,200 index
  sessions, rows with all three US figures; in practice about 2,600 rows, never fewer than the 500 the walk-forward procedure requires).
- Every prediction is stored once and never replaced: `made_at`, the feature values as seen, `train_through` (migration 109).

## 6. Evaluation start and eligible predictions
- Start: sessions from **2026-11-19**.
- A prediction is eligible when it is live, for the market, 1 day, made **after the freeze time** and before 09:15 IST of the session it forecasts, with the outcome known, and **both** models have one for that day (a pair). The candidate has no backfilled history: only forward predictions exist.

## 7. The one primary test
- Delta = Brier(production, 18 features) - Brier(candidate, 7 features) on the same days, same horizon, same outcomes. Positive favours the candidate.
- At least **500 paired forward trading days**. Evaluated **once**, at that endpoint, by `scripts/evaluate_candidate.py`: below 500 pairs it prints only the count; at 500 or more it
  runs the test, writes `docs/forecast/candidate_morning7_primary_evaluation.md` and refuses to run again. No interim looks, no early stopping, no second evaluation at 750 or 1,000 days
  (adding one would need a new pre-registration with its error budget, decided before seeing any 500-day result).
- Interval: two-sided 95%, paired moving-block bootstrap (blocks of 20 days, 10,000 draws, seed 20261119).
- **Promotion is proposed only if the lower bound is strictly above zero** (and then still needs the owner's approval). Otherwise, or if inconclusive: no promotion.

## 8. Reported alongside (diagnostics, never promotion tests)
Brier of each model, Brier skill against the usual tendency known on each day, log loss, calibration curve and slope, accuracy, ROC-AUC, results by trend and volatility regime, counts of
unpaired and missing predictions.

## 9. Training-data policy (owner decision, 2026-11-18)
1. Both models may train on every outcome that has become available before their respective prediction timestamps.
2. This includes historical outcomes from 2025-01-01 onward.
3. Neither model may access future outcomes.
4. Both models use the same training-window policy, minimum sample requirements, retraining schedule and outcome-resolution rules (they run through the same code path, `forecast.tonight`).
5. The 2025-01-01 onward period is never counted as independent confirmation for this candidate.
6. Candidate confirmation begins with the first eligible forward prediction after the candidate specification and implementation are frozen.

Production's training behaviour is unchanged: the experiment changes only the model version under evaluation, not the historical information available to either model.

## 10. Isolation
The candidate is never shown as the forecast, never backfilled, never read by the page, and never touches the sector model. Neither model overwrites the other's rows (separate versions).
It is logged by the same job (`forecast-morning`), whose timer exists in prod only; locally the three commands are run by hand each morning, or no pairs accumulate.

# Volatility forecast `range-ridge-v1`: specification and forward-evaluation rule

**Status: REGISTERED 2026-11-18 (this file is committed before any of its code is written); nothing below changes after this commit.** The freeze record `volatility_v1_freeze.json`, written before the first counted
prediction (the morning of 2026-11-19), adds the time and the SHA-256 of this file and of the code that implements it; only predictions made after the freeze time count.

## 1. What is predicted
- Target: the **next session's Nifty 500 high-low range as a % of that session's open**, 100 x (high - low) / open, from the index's daily candle.
- It is an **expected range**: a point forecast of the average size of the day's high-low range. It is not a direction forecast, not a guaranteed or bounding range, and not a trading signal.
- Not in scope: the absolute close-to-close move (a secondary target in the development work), realised volatility from intraday returns, other indexes, other horizons.

## 2. Model (one fixed configuration, no variants)
- Ridge regression (`alpha = 10`) on the **log** of the target, on the seven inputs below standardised by the training rows' mean and standard deviation.
- Predictions are made in logs and turned back into a level with the training rows' mean of exp(residual) (a smearing factor), so the forecast is the expected range and not its median.
- Version identifier: `range-ridge-v1`. Code: `algo/market/volatility.py` (`fit_ridge`, `predict`) and the live module that calls it.

## 3. Inputs (exactly seven), all known before the open of the session forecast
For the session being forecast (the next after the last completed session D):
| Name | Definition |
|---|---|
| `range_yesterday` | ln of the high-low range % of session D |
| `range_week` | mean of ln range % over the 5 sessions up to and including D |
| `range_month` | mean of ln range % over the 22 sessions up to and including D |
| `move_week` | ln(mean absolute close-to-close move % over the 5 sessions up to D + 0.05) |
| `india_vix` | ln of India VIX's close on D |
| `us_sp_size` | ln(absolute % move of the S&P 500 in the last US session dated before the forecast session + 0.05) |
| `us_vix_change` | % change of the US VIX (^VIX) in that same US session |
Missing values are not imputed: a forecast is made only when all seven exist; otherwise there is no forecast for that day (and it is not counted).

## 4. Training and retraining (walk-forward, earlier sessions only)
- Training rows are sessions with all seven inputs, from the start of the stored series (2016); the model is never fitted on the session it predicts or any later one.
- At least 500 training rows. Refitted **every 21 sessions** by a block rule that depends only on the data: with `p` the position of the forecast session in the row list, the model is fitted on rows `0 .. start-1`
  where `start = 500 + 21 x floor((p - 500) / 21)`; every forecast inside a block uses that one fit. This is exactly the walk-forward procedure of the development evaluation, so a live forecast can be rebuilt from the data alone.
- The training-data policy of the direction candidate applies: every outcome known before the prediction time may be used, including 2025-01-01 onward; the 2025 onward period is never confirmation data; confirmation starts with the first eligible forward prediction after the freeze.

## 5. Prediction time, storage, and independence
- Made at 08:55 IST on the morning of the session it forecasts, by its own job (`range-forecast-morning`), which loads the US closes itself. A failure there does not touch the direction forecasts, and a failure of those does not stop this one.
- It is only made when the last completed Indian session is the session before today (a stale forecast is not made).
- Stored once and never replaced in `range_forecast_log`: version, `as_of`, `made_at`, the seven values, the expected range, `train_through`, `n_train`; the actual range and the target session are filled when it resolves.
- It is never combined with the direction forecasts and plays no part in any decision.

## 6. Baselines (all computed from the data, using only earlier sessions)
1. **Average range of the last 5 sessions** (the most important practical baseline). 2. Average of the last 22 sessions. 3. Yesterday's range. 4. India VIX scaled: a single multiplier on India VIX's close, fitted through the origin on the training rows of the same block rule.

## 7. Evaluation (one primary test, once)
- Eligible: a live `range-ridge-v1` forecast made after the freeze and before 09:15 IST of its target session, with the actual range known.
- **Primary test:** MAE of the 5-session-average baseline minus MAE of the model, on the same sessions (positive favours the model); paired moving-block bootstrap (blocks of 20 sessions, 10,000 draws), two-sided 95%.
  Run **once**, at **500 eligible sessions**, by `scripts/evaluate_range_forecast.py` (below 500 it prints only the count; at 500 it runs the test, writes the report and refuses to run again). No interim looks, no early stop, no extension after
  seeing a result. **The model is called forward-validated only if the interval's lower bound is above zero** (and a decision to use it for anything still needs the owner's approval). Otherwise, or if inconclusive: not validated.
- Power, stated plainly: the development gap against the 5-session average was +0.035 (95% +0.020 to +0.051, 1,724 sessions). At 500 sessions the same gap gives a lower bound above zero roughly two times in three, so an inconclusive result is a real possibility and acceptable.
- **Reported alongside, not tests:** MAE gaps against the other three baselines (paired, descriptive), RMSE, bias, calibration of the level by forecast fifths, results by India VIX regime (cut points 13.9 and 17.2, fixed from the development period) and by calendar half-year, counts of missing and unpaired forecasts.

## 8. Which data the design was chosen on
The inputs, the ridge strength, the baselines and the walk-forward procedure were fixed in advance and the development evaluation (`volatility_dev_2026-11-18.md`) was run once on sessions up to 2024-12-31; no alternative
was tried and nothing was adjusted afterwards. The 2025-onward holdout was not read. It is nonetheless an accessed period for the project as a whole (see `candidate_morning7_disclosure.md`).

## 9. Page
Shown only as a separate, clearly marked research forecast ("Expected Nifty 500 range ... research forecast, forward validation in progress"), with the five-session average beside it. Not presented as a trading signal.

-- The expected-range forecast (algo/market/range_forecast.py, spec docs/forecast/volatility_v1_spec.md): one row per forecast, written once before the open and never
-- replaced; the actual range is filled in when the session has traded. A research forecast under forward validation: not shown as a trading signal.
CREATE TABLE range_forecast_log (
  as_of          DATE NOT NULL,        -- the last completed session the forecast was made after; it forecasts the next one
  model_version  TEXT NOT NULL,
  made_at        TIMESTAMPTZ NOT NULL,
  forecast_range REAL NOT NULL CHECK (forecast_range > 0),   -- the expected high-low range of the next session, % of its open
  features       JSONB NOT NULL,       -- the seven inputs as the model saw them
  train_through  DATE NOT NULL,        -- the last session whose outcome the model had learned from
  n_train        INT NOT NULL,
  target_day     DATE,                 -- the session forecast, once it exists
  actual_range   REAL,                 -- its actual high-low range, % of its open
  resolved_on    DATE,
  PRIMARY KEY (as_of, model_version)
);

-- Every prediction the market model made (TODO 6.5, algo/market/predict.py): probability that a subject (the market, or one sector index) closes higher after
-- `horizon_days` trading days, the evidence behind it, and later what happened. `live` rows are made each evening before the outcome exists; the others are the
-- walk-forward history, each made by a model fitted only on outcomes that were already known on its day (so they can be scored honestly).
CREATE TABLE prediction_log (
  as_of         DATE    NOT NULL,           -- the trading day the prediction was made after (its close and earlier are all it saw)
  subject       TEXT    NOT NULL,           -- 'MARKET' (Nifty 500) or the sector name
  horizon_days  INT     NOT NULL CHECK (horizon_days > 0),
  model_version TEXT    NOT NULL,
  live          BOOLEAN NOT NULL,
  p_up          REAL    NOT NULL CHECK (p_up BETWEEN 0 AND 1),
  evidence      JSONB   NOT NULL DEFAULT '[]',   -- [{feature, value, effect}] the largest pushes on the probability
  outcome_up    BOOLEAN,                    -- NULL until the horizon has passed
  realized      REAL,                       -- the return over the horizon, once known
  resolved_on   DATE,
  PRIMARY KEY (as_of, subject, horizon_days, model_version, live)
);
CREATE INDEX prediction_log_open ON prediction_log (live, as_of) WHERE outcome_up IS NULL;

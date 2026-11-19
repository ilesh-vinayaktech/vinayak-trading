-- Rise odds: a model's estimate, per liquid stock and day, of the chance it beats the median stock over the next 5 sessions (algo/market/rise_odds.py, docs in the module).
-- Walk-forward by construction: a score is only ever made by a model trained on data that ended at least 2 x horizon + 10 days before the day, so the history shown is what the model
-- would really have said then (scripts/study_learned_signals.py found a modest edge out of sample: the top 5% beat the market about 56% of the time over 5 sessions).
CREATE TABLE rise_odds_model (
  version    TEXT        PRIMARY KEY,        -- 'h5-2026-11-18': horizon and the day it may start scoring from
  horizon    SMALLINT    NOT NULL,
  train_end  DATE        NOT NULL,           -- trained on rows at least 2 x horizon + 10 days before this; scores days from here on
  trained_at TIMESTAMPTZ NOT NULL,
  n_rows     INTEGER     NOT NULL,
  features   TEXT[]      NOT NULL,           -- the feature names, in the order the model was fitted on
  payload    BYTEA       NOT NULL,           -- the fitted scikit-learn model (pickle); read back only after its hash matches
  sha256     TEXT        NOT NULL
);
CREATE TABLE rise_odds (
  day           DATE     NOT NULL,           -- IST trading day the score is as of (known at that day's close)
  instrument_id BIGINT   NOT NULL,
  horizon       SMALLINT NOT NULL,
  prob          REAL     NOT NULL CHECK (prob BETWEEN 0 AND 1),   -- the model's chance of beating the median stock over the next `horizon` sessions
  pct           REAL     NOT NULL CHECK (pct BETWEEN 0 AND 100),  -- where that ranks among the stocks scored the same day (100 = the most likely)
  model_version TEXT     NOT NULL REFERENCES rise_odds_model (version),
  PRIMARY KEY (day, instrument_id, horizon)
);
CREATE INDEX rise_odds_instrument ON rise_odds (instrument_id, day);

-- The hold signal: a daily BUY / HOLD / SELL call per liquid stock from a frozen rule (algo/market/hold_signal.py, research in scripts/study_hold_signal_folds.py).
-- A model ranks the day's stocks by their chance of beating the median stock over the next 5 sessions; a flat stock is bought at rank 90 or more, a held stock is sold at rank 20 or less.
-- Walk-forward by construction: the model for a day was trained on data that ended two calendar years before that year began (a day of 2026 uses the model trained to 2024-12-31).
CREATE TABLE hold_signal_model (
  version    TEXT        PRIMARY KEY,        -- 'hold1-2024-12-31': the rule and the day its training data ended
  train_end  DATE        NOT NULL,           -- trained on rows up to this day; scores the year two years after it
  trained_at TIMESTAMPTZ NOT NULL,
  n_rows     INTEGER     NOT NULL,
  features   TEXT[]      NOT NULL,           -- the feature names, in the order the model was fitted on
  payload    BYTEA       NOT NULL,           -- the fitted scikit-learn model (pickle); read back only after its hash matches
  sha256     TEXT        NOT NULL
);
CREATE TABLE hold_signal (
  day           DATE     NOT NULL,           -- IST trading day the call is as of (known at that day's close; acted on at the next open)
  instrument_id BIGINT   NOT NULL,
  prob          REAL     NOT NULL CHECK (prob BETWEEN 0 AND 1),       -- the model's chance of beating the median stock over the next 5 sessions
  rank_pct      REAL     NOT NULL CHECK (rank_pct BETWEEN 0 AND 100), -- where that ranks among the stocks scored the same day (100 = the most likely)
  action        TEXT     NOT NULL CHECK (action IN ('BUY', 'HOLD', 'SELL', 'NONE')),
  in_position   BOOLEAN  NOT NULL,           -- held after this day's decision
  entry_day     DATE,                        -- the day the held position was bought (null while flat)
  model_version TEXT     NOT NULL REFERENCES hold_signal_model (version),
  PRIMARY KEY (day, instrument_id)
);
CREATE INDEX hold_signal_instrument ON hold_signal (instrument_id, day);

-- The swing score per stock on each past day, rebuilt from only what was known that day (TODO 6.2a, algo/screener/history.py), so the score can be tested against what happened next.
-- Stored weekly for the backfill and daily from the nightly job; only stocks that got a score (liquid, three components known) have a row.
CREATE TABLE stock_score_history (
  day           DATE   NOT NULL,            -- IST trading day the score is as of
  instrument_id BIGINT NOT NULL,
  score         REAL   NOT NULL CHECK (score BETWEEN 0 AND 100),
  trend         REAL,                       -- the four components, NULL where the stock had no figure that day
  participation REAL,
  smart_money   REAL,
  quality       REAL,
  PRIMARY KEY (day, instrument_id)
);
CREATE INDEX stock_score_history_instrument ON stock_score_history (instrument_id, day);

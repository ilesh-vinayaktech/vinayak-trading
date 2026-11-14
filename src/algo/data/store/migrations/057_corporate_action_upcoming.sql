-- Corporate actions NSE has announced but whose ex-date has not come yet (known about ten days ahead).
-- Kept apart from corporate_action on purpose: every reader of that table assumes an action has already
-- happened, so a future bonus there would halve today's adjusted prices before the price has dropped.
-- This table is for information (what is coming for a stock) and is REPLACED whole by each daily load, so
-- a revised ex-date never leaves a stale copy. An action moves into corporate_action when its ex-date arrives.
CREATE TABLE corporate_action_upcoming (
  instrument_id BIGINT NOT NULL REFERENCES instrument(instrument_id),
  ex_date       DATE NOT NULL,
  record_date   DATE,
  kind          TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok', 'review')),
  num           NUMERIC,
  den           NUMERIC,
  amount        NUMERIC,
  reason        TEXT NOT NULL DEFAULT '',
  subject       TEXT NOT NULL,
  fetched_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (instrument_id, ex_date, kind, subject)
);
CREATE INDEX corporate_action_upcoming_by_date ON corporate_action_upcoming (ex_date);

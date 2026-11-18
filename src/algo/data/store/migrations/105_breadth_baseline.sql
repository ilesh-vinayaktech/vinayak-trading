-- What each stock's history contributes to today's market breadth, worked out once (after the close, or on demand) so the market zone can be
-- recomputed during the session from live prices without re-reading a year of bars for every stock (that query takes minutes; this takes milliseconds).
-- One generation at a time: `last_bar` is the last trading day the figures include; a live reading is valid only while it is the day before today's session.
CREATE TABLE breadth_baseline (
  last_bar      DATE   NOT NULL,
  instrument_id BIGINT NOT NULL,
  prev_close    NUMERIC NOT NULL,    -- the close on last_bar
  c49           INT NOT NULL,        -- closes available among the last 49 / 199 / 251 / 19 (a window is usable only when full)
  s49           NUMERIC NOT NULL,    -- sum of the last 49 closes; with today's close it makes the 50-day average
  c199          INT NOT NULL,
  s199          NUMERIC NOT NULL,
  c251          INT NOT NULL,
  hi251         NUMERIC NOT NULL,    -- highest and lowest of the last 251 closes: today is a new 52-week high or low against these
  lo251         NUMERIC NOT NULL,
  c19           INT NOT NULL,
  tv19          NUMERIC NOT NULL,    -- sum of close x volume over the last 19 days; with today's it makes the 20-day traded value
  computed_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (last_bar, instrument_id)
);

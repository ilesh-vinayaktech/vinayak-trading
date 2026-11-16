-- The chart's buy/sell decisions of a generated strategy definition for one stock, kept so the next request computes only the days after the last one.
-- A series is keyed by the definition's hash (a definition never changes), the stock and the timeframe; its days are the decisions, not prices.
CREATE TABLE definition_signal_series (
  series_id         BIGSERIAL PRIMARY KEY,
  strategy_id       TEXT NOT NULL,
  version           INTEGER NOT NULL,
  definition_sha256 TEXT NOT NULL CHECK (length(definition_sha256) = 64),
  instrument_id     BIGINT NOT NULL REFERENCES instrument,
  timeframe         TEXT NOT NULL CHECK (timeframe = '1D'),
  first_day         DATE NOT NULL,
  last_day          DATE NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL,
  updated_at        TIMESTAMPTZ NOT NULL,
  UNIQUE (strategy_id, version, definition_sha256, instrument_id, timeframe),
  CHECK (first_day <= last_day)
);
CREATE TABLE definition_signal_day (
  series_id      BIGINT NOT NULL REFERENCES definition_signal_series ON DELETE CASCADE,
  day            DATE NOT NULL,
  ready          BOOLEAN NOT NULL,
  action         TEXT CHECK (action IN ('BUY', 'SELL')),
  reason         TEXT,
  holding_after  BOOLEAN NOT NULL,
  PRIMARY KEY (series_id, day)
);

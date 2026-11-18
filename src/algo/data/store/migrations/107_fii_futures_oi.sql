-- FII open interest in NSE index futures, one row a day (NSE's participant-wise open interest file). Net positioning (long less short) is one of the
-- market zone's signals: FIIs net long is bullish, net short bearish.
CREATE TABLE fii_index_futures_oi (
  day         DATE PRIMARY KEY,
  long_oi     BIGINT NOT NULL CHECK (long_oi >= 0),   -- contracts
  short_oi    BIGINT NOT NULL CHECK (short_oi >= 0),
  ingested_at TIMESTAMPTZ NOT NULL
);

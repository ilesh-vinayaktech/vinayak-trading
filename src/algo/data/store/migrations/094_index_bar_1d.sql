-- Daily OHLC of exchange indexes (NSE and BSE) from Kite, for trend setup. Keyed by exchange+symbol like the Kite dump;
-- no instrument FK (indexes are not tradable instruments in our master). Candles for the latest day are re-upserted.
CREATE TABLE index_bar_1d (
  exchange   TEXT NOT NULL,
  symbol     TEXT NOT NULL,
  trade_date DATE NOT NULL,              -- IST calendar date of the candle
  open       NUMERIC NOT NULL,
  high       NUMERIC NOT NULL,
  low        NUMERIC NOT NULL,
  close      NUMERIC NOT NULL CHECK (close > 0),
  token      BIGINT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (exchange, symbol, trade_date)
);

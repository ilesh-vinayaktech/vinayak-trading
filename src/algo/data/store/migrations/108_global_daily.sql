-- Overnight and global closes the morning forecast reads: US index closes and the US VIX (Yahoo Finance, daily), and GIFT Nifty as it traded at 08:45 IST
-- (Kite minute candles), one value a day. Keyed by the market's own calendar date; a re-read replaces the close (the latest session may still have been moving).
CREATE TABLE global_daily (
  symbol      TEXT NOT NULL,        -- SP500 | NASDAQ | VIXUS | GIFT0845
  day         DATE NOT NULL,
  close       NUMERIC NOT NULL CHECK (close > 0),
  source      TEXT NOT NULL,        -- yahoo | kite
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (symbol, day)
);

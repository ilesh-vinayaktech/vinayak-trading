-- Live index prices and 1-minute index bars (Nifty 50, Sensex, India VIX, ...), captured from the same Kite WebSocket as the stocks.
-- Indices are not instruments (no ISIN, no series), so they have their own small tables keyed by the Kite token.
-- index_live_quote: one row per index, replaced in place every couple of seconds. index_bar_1m: one row per finished minute; `source` is
-- 'live' (built from ticks by the feed) or 'kite' (Kite's historical candle, used to fill a minute the feed missed). Indices have no volume.
CREATE TABLE index_live_quote (
  token       BIGINT PRIMARY KEY,
  exchange    TEXT NOT NULL,
  symbol      TEXT NOT NULL,
  ltp         NUMERIC NOT NULL,
  day_open    NUMERIC,
  day_high    NUMERIC,
  day_low     NUMERIC,
  prev_close  NUMERIC,
  exchange_ts TIMESTAMPTZ,
  updated_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE index_bar_1m (
  token    BIGINT NOT NULL,
  exchange TEXT NOT NULL,
  symbol   TEXT NOT NULL,
  ts       TIMESTAMPTZ NOT NULL,   -- minute open, UTC
  open     NUMERIC NOT NULL,
  high     NUMERIC NOT NULL,
  low      NUMERIC NOT NULL,
  close    NUMERIC NOT NULL,
  source   TEXT NOT NULL CHECK (source IN ('live', 'kite')),
  built_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (token, ts)
);
-- The price a stock had when it was put on the watchlist (live price if the feed was running, else the last close); NULL for older rows.
ALTER TABLE watchlist ADD COLUMN added_price NUMERIC;

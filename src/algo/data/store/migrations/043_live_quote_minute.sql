-- The minute each stock is still building, published with its quote, so an intraday chart can draw the current bar
-- before that minute closes (finished minutes are in live_bar_1m). NULL when no minute is open.
ALTER TABLE live_quote
  ADD COLUMN minute_ts     TIMESTAMPTZ,
  ADD COLUMN minute_open   NUMERIC,
  ADD COLUMN minute_high   NUMERIC,
  ADD COLUMN minute_low    NUMERIC,
  ADD COLUMN minute_volume BIGINT;

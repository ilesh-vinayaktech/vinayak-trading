-- The latest price of each stock the live feed follows, replaced in place every couple of seconds. The charts read it so the
-- current candle moves with the market; a finished minute still goes to live_bar_1m (a bar is written once, a quote is a
-- moving value). day_open / day_high / day_low / prev_close are the exchange's own figures for the day, so they stay right
-- even when the feed joined late; a price-only tick leaves them (and the volume) as they were.
CREATE TABLE live_quote (
  instrument_id BIGINT PRIMARY KEY REFERENCES instrument(instrument_id),
  ltp           NUMERIC NOT NULL,
  day_open      NUMERIC,
  day_high      NUMERIC,
  day_low       NUMERIC,
  prev_close    NUMERIC,
  volume        BIGINT,          -- traded so far today (cumulative)
  exchange_ts   TIMESTAMPTZ,     -- when the exchange stamped the tick, UTC
  updated_at    TIMESTAMPTZ NOT NULL
);

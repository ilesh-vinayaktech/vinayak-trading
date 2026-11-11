-- Live 1-minute bars built from the Kite WebSocket during the session, and the feed service's heartbeat.
-- Kept apart from bar_1m on purpose: bar_1m holds Kite's adjusted historical candles, vetted and versioned; these are
-- bars assembled from ticks, available the moment a minute closes. A day later the historical load can be compared
-- against them. A bar is written once and never revised. `partial` means the minute's volume is understated (the
-- service joined mid-session or the day's running total went backwards).
CREATE TABLE live_bar_1m (
  instrument_id BIGINT NOT NULL REFERENCES instrument(instrument_id),
  ts            TIMESTAMPTZ NOT NULL,   -- minute open, UTC
  open          NUMERIC NOT NULL,
  high          NUMERIC NOT NULL,
  low           NUMERIC NOT NULL,
  close         NUMERIC NOT NULL,
  volume        NUMERIC NOT NULL,
  ticks         INT NOT NULL,
  partial       BOOLEAN NOT NULL,
  built_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (instrument_id, ts)
);

-- One row, replaced every few seconds by the feed service; the operations dashboard reads it.
CREATE TABLE feed_status (
  feed_id      SMALLINT PRIMARY KEY CHECK (feed_id = 1),
  state        TEXT NOT NULL CHECK (state IN ('STARTING', 'CONNECTED', 'RECONNECTING', 'TOKEN_EXPIRED', 'STOPPED')),
  detail       TEXT NOT NULL,
  subscribed   INT NOT NULL,
  last_tick_at TIMESTAMPTZ,
  last_bar_at  TIMESTAMPTZ,
  ticks_total  BIGINT NOT NULL,
  bars_total   BIGINT NOT NULL,
  bad_frames   BIGINT NOT NULL,
  late_ticks   BIGINT NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL
);

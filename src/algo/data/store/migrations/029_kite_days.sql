-- Kite's own DAILY candles (source 'kite' in bar_1d, next to the NSE bhavcopy rows). They carry the whole day's volume,
-- which the minute candles do not (those stop at 15:14 IST). Same adjustment basis as the minutes: adjusted_through is the
-- day the vendor last adjusted for splits and bonuses (NULL on NSE rows, which are raw).
ALTER TABLE bar_1d ADD COLUMN adjusted_through DATE;

CREATE TABLE kite_day_fetch (
  fetch_id         BIGSERIAL PRIMARY KEY,
  instrument_id    BIGINT NOT NULL REFERENCES instrument(instrument_id),
  window_start     DATE NOT NULL,
  window_end       DATE NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('loaded', 'empty', 'failed')),
  candles          INT NOT NULL DEFAULT 0,
  content_sha256   TEXT,
  adjusted_through DATE NOT NULL,
  detail           TEXT NOT NULL DEFAULT '',
  fetched_at       TIMESTAMPTZ NOT NULL,
  raw_sha256       TEXT,
  UNIQUE (instrument_id, window_start, window_end)
);

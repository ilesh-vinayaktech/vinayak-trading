-- 1-minute bars from Zerodha Kite. Kite serves prices and volumes ADJUSTED for splits and bonuses as of the fetch
-- date, so every row records `adjusted_through` (the day its prices were last adjusted): corporate actions with an
-- ex-date AFTER that day still have to be applied by a reader; those on or before it must not be applied again.
-- bar_1d (NSE bhavcopy, raw prices) is left untouched as the backup copy.
CREATE TABLE bar_1m (
  instrument_id    BIGINT NOT NULL REFERENCES instrument(instrument_id),
  ts               TIMESTAMPTZ NOT NULL,                  -- candle open, UTC
  open             NUMERIC NOT NULL,
  high             NUMERIC NOT NULL,
  low              NUMERIC NOT NULL,
  close            NUMERIC NOT NULL,
  volume           NUMERIC NOT NULL,
  oi               NUMERIC,
  source           TEXT NOT NULL,
  adjusted_through DATE NOT NULL,
  dataset_version  INT NOT NULL DEFAULT 1,
  ingested_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (instrument_id, ts, source, dataset_version)
);
-- A compressed hypertable where TimescaleDB is installed (production). The integration-test harness rebuilds the schema
-- each test, which removes the extension's functions, so there the table stays a plain table and only the logic is tested.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'create_hypertable') THEN
    PERFORM create_hypertable('bar_1m', 'ts', chunk_time_interval => INTERVAL '90 days');
    ALTER TABLE bar_1m SET (
      timescaledb.compress,
      timescaledb.compress_segmentby = 'instrument_id, source, dataset_version',
      timescaledb.compress_orderby = 'ts'
    );
    PERFORM add_compression_policy('bar_1m', INTERVAL '7 days');
  END IF;
END
$$;

-- Kite's own instrument tokens for the securities we load (the dump has no ISIN: the link is by NSE symbol).
CREATE TABLE kite_instrument (
  instrument_token BIGINT PRIMARY KEY,
  exchange_token   BIGINT NOT NULL,
  tradingsymbol    TEXT NOT NULL,
  name             TEXT NOT NULL,
  instrument_id    BIGINT REFERENCES instrument(instrument_id),
  refreshed_at     TIMESTAMPTZ NOT NULL
);

-- One row per instrument and request window: what was asked, what came back, and the adjustment basis it carries.
CREATE TABLE kite_fetch (
  fetch_id         BIGSERIAL PRIMARY KEY,
  instrument_id    BIGINT NOT NULL REFERENCES instrument(instrument_id),
  window_start     DATE NOT NULL,
  window_end       DATE NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('loaded', 'empty', 'failed')),
  candles          INT NOT NULL DEFAULT 0,
  content_sha256   TEXT,                                   -- of the candles as parsed (the raw JSON is not kept: re-fetchable)
  adjusted_through DATE NOT NULL,
  detail           TEXT NOT NULL DEFAULT '',
  fetched_at       TIMESTAMPTZ NOT NULL,
  UNIQUE (instrument_id, window_start, window_end)
);

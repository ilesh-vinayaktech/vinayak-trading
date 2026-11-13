-- The screener's table (algo.screener.snapshot): one row per listed stock, rebuilt by the scheduled screener-refresh job
-- (about 30-50 s of calculation) so a screen only reads it. Replaced whole on each refresh; figures are stored as text.
CREATE TABLE screener_snapshot (
  instrument_id BIGINT PRIMARY KEY REFERENCES instrument(instrument_id),
  as_of         DATE NOT NULL,           -- the last daily bar the row was built from
  row           JSONB NOT NULL,
  built_at      TIMESTAMPTZ NOT NULL
);

-- Daily bars from EOD sources. Versioned: a changed payload adds a new dataset_version.
CREATE TABLE bar_1d (
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  ts TIMESTAMPTZ NOT NULL,           -- bar-open (session open) in UTC
  open NUMERIC NOT NULL, high NUMERIC NOT NULL, low NUMERIC NOT NULL, close NUMERIC NOT NULL,
  volume NUMERIC NOT NULL,
  series TEXT, prev_close NUMERIC, delivery_qty NUMERIC,
  source TEXT NOT NULL,
  dataset_version INT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (instrument_id, ts, source, dataset_version)
);

-- One row per load attempt: audit trail + quarantine record.
CREATE TABLE partition_load (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL, dataset TEXT NOT NULL, partition DATE NOT NULL,
  raw_version INT NOT NULL, checksum TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('loaded','noop','quarantined')),
  dataset_version INT,
  detail JSONB NOT NULL DEFAULT '{}',
  at TIMESTAMPTZ NOT NULL
);

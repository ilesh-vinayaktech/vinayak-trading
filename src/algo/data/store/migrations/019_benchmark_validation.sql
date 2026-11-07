-- Evidence that a stored benchmark series was validated, kept SEPARATE from the observations:
-- the report, the data hashes and the independent (factsheet) reconciliation it relied on.
CREATE TABLE benchmark_validation (
  validation_id     BIGSERIAL PRIMARY KEY,
  benchmark_id      BIGINT NOT NULL REFERENCES benchmark(benchmark_id),
  created_at        TIMESTAMPTZ NOT NULL,
  dataset_hash      TEXT NOT NULL,             -- data/benchmark.py dataset_hash at validation time
  normalized_sha256 TEXT NOT NULL,             -- providers/niftyindices_tri normalized hash of the capture
  factsheet_sha256  TEXT,                      -- the document the returns were reconciled against
  passed            BOOLEAN NOT NULL,
  report            JSONB NOT NULL,
  unresolved        JSONB NOT NULL             -- what is explicitly NOT verified
);

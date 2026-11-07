-- Benchmarks: index level series, immutable once stored. Price, total-return (gross) and net
-- total-return series are different benchmarks and are never mixed.
CREATE TABLE benchmark (
  benchmark_id        BIGSERIAL PRIMARY KEY,
  name                TEXT NOT NULL,
  provider            TEXT NOT NULL,
  index_symbol        TEXT NOT NULL,
  return_type         TEXT NOT NULL CHECK (return_type IN ('PRICE', 'TOTAL_RETURN', 'NET_TOTAL_RETURN')),
  currency            TEXT NOT NULL DEFAULT 'INR',
  frequency           TEXT NOT NULL DEFAULT 'daily' CHECK (frequency = 'daily'),
  methodology_version TEXT NOT NULL,
  valid_from          DATE,
  valid_until         DATE,
  UNIQUE (index_symbol, return_type, methodology_version)
);

CREATE TABLE benchmark_observation (
  benchmark_id     BIGINT NOT NULL REFERENCES benchmark(benchmark_id),
  observation_date DATE NOT NULL,
  close_value      NUMERIC NOT NULL CHECK (close_value > 0),
  source           TEXT NOT NULL,
  source_timestamp TIMESTAMPTZ NOT NULL,
  ingested_at      TIMESTAMPTZ NOT NULL,
  raw_hash         TEXT NOT NULL,            -- sha256 of the raw file the value came from
  PRIMARY KEY (benchmark_id, observation_date)
);

CREATE FUNCTION benchmark_observation_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'benchmark observations are immutable';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER benchmark_observation_no_change
  BEFORE UPDATE OR DELETE ON benchmark_observation
  FOR EACH ROW EXECUTE FUNCTION benchmark_observation_immutable();

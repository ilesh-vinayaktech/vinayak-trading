-- A named, sealed data snapshot: "this run read exactly this data". It records the moment (cutoff_time: everything ingested
-- later is invisible), the price source and cutoff, the instruments, a hash of their bars, corporate actions and decisions
-- at that moment, other pinned fingerprints (calendar, Kite freeze in force, cost schedule, code commit, strategy config),
-- and a manifest of the raw files that fed the data. Both tables are append-only; verify recomputes the hash.
CREATE TABLE data_snapshot (
  snapshot_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at     TIMESTAMPTZ NOT NULL,
  cutoff_time    TIMESTAMPTZ NOT NULL,
  price_source   TEXT NOT NULL CHECK (price_source IN ('kite', 'bhavcopy')),
  price_cutoff   DATE,
  instrument_ids BIGINT[] NOT NULL CHECK (cardinality(instrument_ids) > 0),
  snapshot_hash  TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  pins           JSONB NOT NULL,
  status         TEXT NOT NULL CHECK (status = 'sealed'),
  note           TEXT NOT NULL CHECK (length(btrim(note)) > 0),
  CHECK (price_cutoff IS NULL OR price_source = 'bhavcopy')
);

CREATE TABLE snapshot_partition (
  snapshot_id     UUID NOT NULL REFERENCES data_snapshot(snapshot_id),
  source          TEXT NOT NULL,
  dataset         TEXT NOT NULL,
  partition_date  DATE NOT NULL,
  load_id         BIGINT NOT NULL,
  raw_version     INT NOT NULL,
  checksum        TEXT NOT NULL,
  status          TEXT NOT NULL,
  dataset_version INT,
  PRIMARY KEY (snapshot_id, source, dataset, partition_date)
);

CREATE FUNCTION data_snapshot_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER data_snapshot_no_change BEFORE UPDATE OR DELETE ON data_snapshot
  FOR EACH ROW EXECUTE FUNCTION data_snapshot_immutable();
CREATE TRIGGER snapshot_partition_no_change BEFORE UPDATE OR DELETE ON snapshot_partition
  FOR EACH ROW EXECUTE FUNCTION data_snapshot_immutable();

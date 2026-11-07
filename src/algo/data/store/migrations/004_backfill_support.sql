-- 'not_published' = provider had no file for a weekday (holiday, or incident if a trading day).
ALTER TABLE partition_load DROP CONSTRAINT partition_load_status_check;
ALTER TABLE partition_load ADD CONSTRAINT partition_load_status_check
  CHECK (status IN ('loaded','noop','quarantined','not_published'));
ALTER TABLE partition_load ALTER COLUMN raw_version DROP NOT NULL;
ALTER TABLE partition_load ALTER COLUMN checksum DROP NOT NULL;
CREATE INDEX partition_load_lookup ON partition_load (source, dataset, partition);

-- Index constituents as honest dated snapshots (we only have current lists, not history).
CREATE TABLE index_snapshot (
  index_id TEXT NOT NULL,
  as_of DATE NOT NULL,
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  PRIMARY KEY (index_id, as_of, instrument_id)
);

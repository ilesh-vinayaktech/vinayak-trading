-- 'supplement': rows for symbols added to the master AFTER the day was loaded were inserted into the
-- day's existing dataset version (same raw file, no new version).
ALTER TABLE partition_load DROP CONSTRAINT partition_load_status_check;
ALTER TABLE partition_load ADD CONSTRAINT partition_load_status_check
  CHECK (status IN ('loaded', 'noop', 'quarantined', 'not_published', 'supplement'));

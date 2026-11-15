-- One row per data-quality finding per run: which check, what it looked at, what it found. Append-only (a finding is history, not state):
-- the same check run again adds rows. A run with nothing to report adds one PASS row, so "ran and was clean" is distinguishable from "did not run".
CREATE TABLE dq_result (
  result_id  BIGSERIAL PRIMARY KEY,
  run_at     TIMESTAMPTZ NOT NULL,
  check_name TEXT NOT NULL CHECK (length(check_name) > 0),
  scope      TEXT NOT NULL,            -- what was examined, e.g. 'nse bar_1d since 2026-10-16'
  subject    TEXT,                     -- the day, file or instrument the finding is about; NULL for PASS
  status     TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
  detail     TEXT NOT NULL
);
CREATE INDEX dq_result_check ON dq_result (check_name, run_at DESC);
CREATE FUNCTION dq_result_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'dq_result is insert-only: a finding is never changed or removed';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER dq_result_insert_only BEFORE UPDATE OR DELETE ON dq_result FOR EACH ROW EXECUTE FUNCTION dq_result_insert_only();

-- The global research holdout lock (docs/vti-alignment.md section 3). The lock's dates live in config/research_holdout.json AND
-- here as a hash: every research reader compares the file with the newest row and fails closed when they differ, so editing the
-- file alone cannot open the holdout. Append-only: a change is a new row with who and why.
CREATE TABLE research_lock (
  lock_id         BIGSERIAL PRIMARY KEY,
  config_sha256   TEXT NOT NULL,
  development_end DATE NOT NULL,
  holdout_start   DATE NOT NULL,
  holdout_end     DATE NOT NULL,
  set_by          TEXT NOT NULL CHECK (set_by <> ''),
  reason          TEXT NOT NULL CHECK (reason <> ''),
  set_at          TIMESTAMPTZ NOT NULL,
  CHECK (development_end < holdout_start AND holdout_start <= holdout_end)
);
CREATE FUNCTION research_lock_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'research_lock is append-only: add a new row';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER research_lock_no_change BEFORE UPDATE OR DELETE ON research_lock
  FOR EACH ROW EXECUTE FUNCTION research_lock_immutable();

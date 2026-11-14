-- The data a study was registered against, sealed by its first run (docs/vti-phase1-spec.md work item B). The manifest lists every
-- input (frozen history, the bars, corporate actions and decisions of the universe as the database held them at the study's
-- `known_at`, the universe, the window, the cost schedules) and `dataset_sha256` is its hash. Written once: every later run
-- recomputes the manifest and refuses to continue if it differs.
CREATE TABLE study_dataset (
  experiment_id  BIGINT PRIMARY KEY REFERENCES experiment(experiment_id),
  dataset_sha256 TEXT NOT NULL CHECK (dataset_sha256 <> ''),
  manifest       JSONB NOT NULL,
  sealed_at      TIMESTAMPTZ NOT NULL
);
CREATE FUNCTION study_dataset_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'study_dataset is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER study_dataset_no_change BEFORE UPDATE OR DELETE ON study_dataset
  FOR EACH ROW EXECUTE FUNCTION study_dataset_immutable();

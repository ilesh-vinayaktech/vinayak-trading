-- Historical validation of a feature against one dataset (docs/vti-phase1-spec.md, item F). Insert-only, like the rest of the feature tables:
-- the report that justified a status change is kept as it was, and the status row names it.
CREATE TABLE feature_validation (
  report_id      BIGSERIAL PRIMARY KEY,
  feature_id     BIGINT NOT NULL REFERENCES feature_definition,
  dataset_sha256 TEXT NOT NULL,
  passed         BOOLEAN NOT NULL,
  report         JSONB NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL,
  created_by     TEXT NOT NULL CHECK (length(created_by) > 0)
);
CREATE INDEX feature_validation_feature ON feature_validation (feature_id, report_id DESC);
CREATE TRIGGER feature_validation_insert_only BEFORE UPDATE OR DELETE ON feature_validation FOR EACH ROW EXECUTE FUNCTION feature_tables_insert_only();

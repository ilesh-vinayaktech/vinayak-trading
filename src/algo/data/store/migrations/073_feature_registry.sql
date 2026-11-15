-- Feature registry (docs/vti-phase1-spec.md, item C). Everything here is insert-only: a definition, its status history, a materialisation (a run
-- and its values) are never updated or deleted, so the same feature, instrument and day can have several immutable materialisations, one per dataset.
CREATE TABLE feature_definition (
  feature_id      BIGSERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  version         TEXT NOT NULL,
  manifest        JSONB NOT NULL,
  manifest_sha256 TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (name, version)
);

-- A feature's status moves only by a new row: DRAFT (usable by nobody), USABLE (a study may name it) or BLOCKED (its inputs are not ready).
CREATE TABLE feature_status (
  status_id  BIGSERIAL PRIMARY KEY,
  feature_id BIGINT NOT NULL REFERENCES feature_definition,
  status     TEXT NOT NULL CHECK (status IN ('DRAFT', 'USABLE', 'BLOCKED')),
  reason     TEXT NOT NULL CHECK (length(reason) > 0),
  set_by     TEXT NOT NULL CHECK (length(set_by) > 0),
  at         TIMESTAMPTZ NOT NULL
);
CREATE INDEX feature_status_latest ON feature_status (feature_id, status_id DESC);

-- One run per feature and calendar month and dataset. A failed month is recorded and invalidates nothing; at most one COMPLETE run per
-- (feature, month, dataset) exists.
CREATE TABLE feature_run (
  run_id         BIGSERIAL PRIMARY KEY,
  feature_id     BIGINT NOT NULL REFERENCES feature_definition,
  month          DATE NOT NULL CHECK (EXTRACT(DAY FROM month) = 1),
  dataset_sha256 TEXT NOT NULL,
  code_commit    TEXT NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('complete', 'failed')),
  rows           INTEGER NOT NULL DEFAULT 0,
  result_sha256  TEXT,
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ NOT NULL,
  error          TEXT,
  CHECK ((status = 'complete') = (result_sha256 IS NOT NULL))
);
CREATE UNIQUE INDEX feature_run_one_complete ON feature_run (feature_id, month, dataset_sha256) WHERE status = 'complete';

CREATE TABLE feature_value (
  run_id        BIGINT NOT NULL REFERENCES feature_run,
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  day           DATE NOT NULL,
  value         NUMERIC NOT NULL,
  available_at  TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (run_id, instrument_id, day)
);

CREATE FUNCTION feature_tables_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is insert-only: a feature definition, status, run or value is never changed or removed', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER feature_definition_insert_only BEFORE UPDATE OR DELETE ON feature_definition FOR EACH ROW EXECUTE FUNCTION feature_tables_insert_only();
CREATE TRIGGER feature_status_insert_only BEFORE UPDATE OR DELETE ON feature_status FOR EACH ROW EXECUTE FUNCTION feature_tables_insert_only();
CREATE TRIGGER feature_run_insert_only BEFORE UPDATE OR DELETE ON feature_run FOR EACH ROW EXECUTE FUNCTION feature_tables_insert_only();
CREATE TRIGGER feature_value_insert_only BEFORE UPDATE OR DELETE ON feature_value FOR EACH ROW EXECUTE FUNCTION feature_tables_insert_only();

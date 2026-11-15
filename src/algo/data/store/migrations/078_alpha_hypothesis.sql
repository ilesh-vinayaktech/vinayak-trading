-- The alpha hypothesis registry (plan.md section 6.4, phase 2). One row per feature, horizon and discovery batch, insert-only:
-- a hypothesis that failed stays on the books (it counts toward the number of tests ever run, which is what corrects the next batch's p-values),
-- and a verdict is never rewritten. The evidence is whatever the discovery run measured; nothing here is typed in by hand.
CREATE TABLE alpha_hypothesis (
  hypothesis_id     BIGSERIAL PRIMARY KEY,
  batch_id          INTEGER NOT NULL,
  feature_name      TEXT NOT NULL,
  feature_version   TEXT NOT NULL,
  horizon_days      INTEGER NOT NULL CHECK (horizon_days > 0),
  method            TEXT NOT NULL CHECK (method = 'RANK_IC'),
  dataset_sha256    TEXT NOT NULL,
  research_status   TEXT NOT NULL CHECK (research_status IN ('CANDIDATE', 'REJECTED')),
  validation_status TEXT NOT NULL CHECK (validation_status IN ('PENDING', 'NOT_APPLICABLE')),
  evidence          JSONB NOT NULL,
  evidence_sha256   TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL,
  CHECK ((research_status = 'CANDIDATE') = (validation_status = 'PENDING')),
  UNIQUE (batch_id, feature_name, feature_version, horizon_days)
);
CREATE INDEX alpha_hypothesis_feature ON alpha_hypothesis (feature_name, feature_version, horizon_days);
CREATE FUNCTION alpha_hypothesis_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'alpha_hypothesis is insert-only: a hypothesis, failed or not, is never changed or removed';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER alpha_hypothesis_insert_only BEFORE UPDATE OR DELETE ON alpha_hypothesis FOR EACH ROW EXECUTE FUNCTION alpha_hypothesis_insert_only();

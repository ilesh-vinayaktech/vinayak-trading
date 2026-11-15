-- Capital allocation recommendations (plan.md phase 5): what the allocator was given, what it advised, and who asked. Insert-only, so every change of
-- advice is auditable. A recommendation moves no money; applying one is a separate, human step.
CREATE TABLE allocation_recommendation (
  recommendation_id BIGSERIAL PRIMARY KEY,
  method            TEXT NOT NULL CHECK (method IN ('EQUAL_RISK', 'RISK_PARITY')),
  limits            JSONB NOT NULL,
  target_vol        DOUBLE PRECISION CHECK (target_vol IS NULL OR target_vol > 0),
  health            JSONB NOT NULL,
  inputs_sha256     TEXT NOT NULL CHECK (length(inputs_sha256) = 64),
  weights           JSONB NOT NULL,
  cash              DOUBLE PRECISION NOT NULL CHECK (cash >= 0 AND cash <= 1),
  notes             JSONB NOT NULL,
  risk_contribution JSONB NOT NULL,
  created_by        TEXT NOT NULL CHECK (length(btrim(created_by)) > 0),
  created_at        TIMESTAMPTZ NOT NULL
);
CREATE FUNCTION allocation_recommendation_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'allocation_recommendation is insert-only: advice is never changed or removed; record a new one';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER allocation_recommendation_insert_only BEFORE UPDATE OR DELETE ON allocation_recommendation FOR EACH ROW EXECUTE FUNCTION allocation_recommendation_insert_only();

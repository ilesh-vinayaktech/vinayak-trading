-- Experiments on strategy definitions (plan.md section 8). An experiment is a base definition (a registered, immutable version) and a grid of rule changes;
-- each combination is a trial. EVERY trial is kept, including the ones that were not valid definitions (SKIPPED) and the ones that could not run (FAILED),
-- because the number of tries is what the multiple-testing correction counts. Both tables are insert-only.
CREATE TABLE factory_experiment (
  experiment_id  BIGSERIAL PRIMARY KEY,
  base_strategy_id TEXT NOT NULL,
  base_version   INTEGER NOT NULL,
  base_sha256    TEXT NOT NULL CHECK (length(base_sha256) = 64),
  grid           JSONB NOT NULL,
  window_start   DATE NOT NULL,
  window_end     DATE NOT NULL,
  trials_planned INTEGER NOT NULL CHECK (trials_planned >= 1),
  created_by     TEXT NOT NULL CHECK (length(btrim(created_by)) > 0),
  created_at     TIMESTAMPTZ NOT NULL,
  CHECK (window_end > window_start),
  FOREIGN KEY (base_strategy_id, base_version) REFERENCES strategy_definition (strategy_id, version)
);
CREATE TABLE factory_trial (
  trial_id          BIGSERIAL PRIMARY KEY,
  experiment_id     BIGINT NOT NULL REFERENCES factory_experiment,
  ordinal           INTEGER NOT NULL CHECK (ordinal >= 0),
  overrides         JSONB NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('DONE', 'SKIPPED', 'FAILED')),
  reason            TEXT,
  definition_sha256 TEXT,
  metrics           JSONB,
  result_hash       TEXT,
  returns           JSONB,
  created_at        TIMESTAMPTZ NOT NULL,
  UNIQUE (experiment_id, ordinal),
  CHECK ((status = 'DONE') = (metrics IS NOT NULL AND result_hash IS NOT NULL AND returns IS NOT NULL AND definition_sha256 IS NOT NULL)),
  CHECK ((status = 'DONE') OR (reason IS NOT NULL AND length(btrim(reason)) > 0))
);
CREATE FUNCTION factory_experiment_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is insert-only: an experiment and its trials are never changed or removed', TG_TABLE_NAME;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER factory_experiment_insert_only BEFORE UPDATE OR DELETE ON factory_experiment FOR EACH ROW EXECUTE FUNCTION factory_experiment_insert_only();
CREATE TRIGGER factory_trial_insert_only BEFORE UPDATE OR DELETE ON factory_trial FOR EACH ROW EXECUTE FUNCTION factory_experiment_insert_only();

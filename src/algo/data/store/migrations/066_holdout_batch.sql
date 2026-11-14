-- The one global holdout evaluation (docs/vti-alignment.md section 3). At most ONE batch ever exists (the unique `only_one`
-- column), so no second batch can be registered once the first is, whatever its state. States move forward only:
--   REGISTERED -> FROZEN -> EVALUATING -> CONSUMED | EVALUATION_FAILED
-- The manifest is stored when the batch is FROZEN and can never change. The holdout counts as consumed from the moment the batch
-- is EVALUATING (that move is committed before any holdout data is read). Verdicts are written once, with the move to CONSUMED.
CREATE TABLE holdout_batch (
  batch_id          BIGSERIAL PRIMARY KEY,
  only_one          BOOLEAN NOT NULL DEFAULT TRUE CHECK (only_one) CONSTRAINT holdout_batch_only_one UNIQUE,
  state             TEXT NOT NULL CHECK (state IN ('REGISTERED', 'FROZEN', 'EVALUATING', 'CONSUMED', 'EVALUATION_FAILED')),
  lock_id           BIGINT NOT NULL REFERENCES research_lock(lock_id),
  evaluator_version TEXT NOT NULL CHECK (evaluator_version <> ''),
  registered_by     TEXT NOT NULL CHECK (registered_by <> ''),
  manifest          JSONB,
  manifest_sha256   TEXT,
  failure           TEXT,
  registered_at     TIMESTAMPTZ NOT NULL,
  frozen_at         TIMESTAMPTZ,
  evaluating_at     TIMESTAMPTZ,
  finished_at       TIMESTAMPTZ,
  CHECK ((state = 'REGISTERED') = (manifest_sha256 IS NULL)),
  CHECK (manifest_sha256 IS NULL OR manifest IS NOT NULL)
);

CREATE FUNCTION holdout_batch_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'holdout_batch cannot be deleted';
  END IF;
  IF NEW.batch_id <> OLD.batch_id OR NEW.lock_id <> OLD.lock_id OR NEW.evaluator_version <> OLD.evaluator_version
     OR NEW.registered_by <> OLD.registered_by OR NEW.registered_at <> OLD.registered_at THEN
    RAISE EXCEPTION 'holdout_batch: identity fields cannot change';
  END IF;
  IF OLD.manifest_sha256 IS NOT NULL AND (NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 OR NEW.manifest IS DISTINCT FROM OLD.manifest) THEN
    RAISE EXCEPTION 'holdout_batch: a frozen manifest cannot change';
  END IF;
  IF NOT ((OLD.state = 'REGISTERED' AND NEW.state = 'FROZEN')
       OR (OLD.state = 'FROZEN' AND NEW.state = 'EVALUATING')
       OR (OLD.state = 'EVALUATING' AND NEW.state IN ('CONSUMED', 'EVALUATION_FAILED'))) THEN
    RAISE EXCEPTION 'holdout_batch: % -> % is not a forward move', OLD.state, NEW.state;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_batch_forward_only BEFORE UPDATE OR DELETE ON holdout_batch
  FOR EACH ROW EXECUTE FUNCTION holdout_batch_guard();

-- What research code may read after the evaluation: one of four verdicts per candidate and gate, never a figure.
CREATE TABLE holdout_verdict (
  batch_id     BIGINT NOT NULL REFERENCES holdout_batch(batch_id),
  candidate_id TEXT NOT NULL CHECK (candidate_id <> ''),
  gate         TEXT NOT NULL CHECK (gate <> ''),
  verdict      TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'INSUFFICIENT_EVIDENCE', 'NOT_APPLICABLE')),
  PRIMARY KEY (batch_id, candidate_id, gate)
);
-- The detailed report: for the owner through the portal only. No research-facing accessor exists.
CREATE TABLE holdout_report (
  batch_id BIGINT PRIMARY KEY REFERENCES holdout_batch(batch_id),
  report   JSONB NOT NULL
);

CREATE FUNCTION holdout_results_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
  END IF;
  IF (SELECT state FROM holdout_batch WHERE batch_id = NEW.batch_id) <> 'EVALUATING' THEN
    RAISE EXCEPTION '% can only be written while the batch is EVALUATING', TG_TABLE_NAME;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_verdict_guard BEFORE INSERT OR UPDATE OR DELETE ON holdout_verdict
  FOR EACH ROW EXECUTE FUNCTION holdout_results_guard();
CREATE TRIGGER holdout_report_guard BEFORE INSERT OR UPDATE OR DELETE ON holdout_report
  FOR EACH ROW EXECUTE FUNCTION holdout_results_guard();

-- Once any batch exists the window can no longer be changed.
CREATE FUNCTION research_lock_frozen_by_batch() RETURNS trigger AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM holdout_batch) THEN
    RAISE EXCEPTION 'research_lock cannot change once a holdout batch exists';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER research_lock_batch_freeze BEFORE INSERT ON research_lock
  FOR EACH ROW EXECUTE FUNCTION research_lock_frozen_by_batch();

-- Holdout policy v3 (docs/holdout-policy-v3.md sections 3, 7): append-only batches over a fixed lifetime budget of 30 candidate slots.
-- Replaces the "one batch ever" rule and the "consumed at EVALUATING" point of migration 066: a slot is consumed when the durable first-read marker is committed.
ALTER TABLE holdout_batch DROP CONSTRAINT holdout_batch_only_one;
ALTER TABLE holdout_batch DROP COLUMN only_one;
ALTER TABLE holdout_batch ADD COLUMN first_read_at TIMESTAMPTZ;
ALTER TABLE holdout_batch ADD COLUMN methodology_version TEXT;

-- One row per candidate per batch: its permanent slot state and its bootstrap seed (128 bits, 32 hex digits, committed at freeze, never changed).
CREATE TABLE holdout_candidate (
  batch_id     BIGINT NOT NULL REFERENCES holdout_batch(batch_id),
  candidate_id TEXT NOT NULL CHECK (candidate_id <> ''),
  state        TEXT NOT NULL CHECK (state IN ('RESERVED', 'CONSUMED', 'RELEASED')),
  seed         TEXT NOT NULL CHECK (seed ~ '^[0-9a-f]{32}$'),
  reserved_at  TIMESTAMPTZ NOT NULL,
  settled_at   TIMESTAMPTZ,
  PRIMARY KEY (batch_id, candidate_id),
  CHECK ((state = 'RESERVED') = (settled_at IS NULL))
);
-- A candidate holds at most one live slot, ever: a consumed candidate can never be tested again, a released one can.
CREATE UNIQUE INDEX holdout_candidate_one_live_slot ON holdout_candidate (candidate_id) WHERE state IN ('RESERVED', 'CONSUMED');

CREATE FUNCTION holdout_candidate_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'holdout_candidate cannot be deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.state <> 'RESERVED' THEN
      RAISE EXCEPTION 'a candidate enters the ledger RESERVED';
    END IF;
    PERFORM pg_advisory_xact_lock(7203002);  -- two batches frozen at once cannot both fit into the last slots
    IF (SELECT count(*) FROM holdout_candidate WHERE state IN ('RESERVED', 'CONSUMED')) >= 30 THEN
      RAISE EXCEPTION 'the holdout budget of 30 candidate slots is used up';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.batch_id <> OLD.batch_id OR NEW.candidate_id <> OLD.candidate_id OR NEW.seed <> OLD.seed OR NEW.reserved_at <> OLD.reserved_at THEN
    RAISE EXCEPTION 'holdout_candidate: identity and seed cannot change';
  END IF;
  IF NOT (OLD.state = 'RESERVED' AND NEW.state IN ('CONSUMED', 'RELEASED')) THEN
    RAISE EXCEPTION 'holdout_candidate: % -> % is not allowed (a settled slot is permanent)', OLD.state, NEW.state;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_candidate_rules BEFORE INSERT OR UPDATE OR DELETE ON holdout_candidate
  FOR EACH ROW EXECUTE FUNCTION holdout_candidate_guard();

-- The first-read marker: set once, only while EVALUATING. Committing it consumes every reserved slot of the batch.
-- A batch that fails before the marker releases its slots; after it, they stay consumed.
CREATE OR REPLACE FUNCTION holdout_batch_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'holdout_batch cannot be deleted';
  END IF;
  IF NEW.batch_id <> OLD.batch_id OR NEW.lock_id <> OLD.lock_id OR NEW.evaluator_version <> OLD.evaluator_version
     OR NEW.registered_by <> OLD.registered_by OR NEW.registered_at <> OLD.registered_at THEN
    RAISE EXCEPTION 'holdout_batch: identity fields cannot change';
  END IF;
  IF OLD.manifest_sha256 IS NOT NULL AND (NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 OR NEW.manifest IS DISTINCT FROM OLD.manifest
     OR NEW.methodology_version IS DISTINCT FROM OLD.methodology_version) THEN
    RAISE EXCEPTION 'holdout_batch: a frozen manifest cannot change';
  END IF;
  IF OLD.first_read_at IS NOT NULL AND NEW.first_read_at IS DISTINCT FROM OLD.first_read_at THEN
    RAISE EXCEPTION 'holdout_batch: the first-read marker cannot change';
  END IF;
  IF NEW.first_read_at IS NOT NULL AND OLD.first_read_at IS NULL THEN
    IF NEW.state <> 'EVALUATING' THEN
      RAISE EXCEPTION 'holdout_batch: the first-read marker is written while EVALUATING';
    END IF;
    UPDATE holdout_candidate SET state = 'CONSUMED', settled_at = NEW.first_read_at WHERE batch_id = NEW.batch_id AND state = 'RESERVED';
  END IF;
  IF NEW.state <> OLD.state THEN
    IF NOT ((OLD.state = 'REGISTERED' AND NEW.state = 'FROZEN')
         OR (OLD.state = 'FROZEN' AND NEW.state = 'EVALUATING')
         OR (OLD.state = 'EVALUATING' AND NEW.state IN ('CONSUMED', 'EVALUATION_FAILED'))) THEN
      RAISE EXCEPTION 'holdout_batch: % -> % is not a forward move', OLD.state, NEW.state;
    END IF;
    IF NEW.state = 'CONSUMED' AND NEW.first_read_at IS NULL THEN
      RAISE EXCEPTION 'holdout_batch: no result without the first-read marker';
    END IF;
    IF NEW.state = 'EVALUATION_FAILED' AND NEW.first_read_at IS NULL THEN
      UPDATE holdout_candidate SET state = 'RELEASED', settled_at = NEW.finished_at WHERE batch_id = NEW.batch_id AND state = 'RESERVED';
    END IF;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- Exclusions at a cutoff (section 3): only for one of four reasons fixed in the policy, with evidence, and never changed. An excluded candidate consumes no slot.
CREATE TABLE holdout_exclusion (
  candidate_id TEXT PRIMARY KEY CHECK (candidate_id <> ''),
  reason       SMALLINT NOT NULL CHECK (reason BETWEEN 1 AND 4),
  evidence     TEXT NOT NULL CHECK (evidence <> ''),
  excluded_at  TIMESTAMPTZ NOT NULL
);
CREATE FUNCTION holdout_exclusion_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'holdout_exclusion is append-only';
  END IF;
  IF EXISTS (SELECT 1 FROM holdout_candidate WHERE candidate_id = NEW.candidate_id AND state IN ('RESERVED', 'CONSUMED')) THEN
    RAISE EXCEPTION 'a candidate in a frozen batch cannot be excluded';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_exclusion_rules BEFORE INSERT OR UPDATE OR DELETE ON holdout_exclusion
  FOR EACH ROW EXECUTE FUNCTION holdout_exclusion_guard();

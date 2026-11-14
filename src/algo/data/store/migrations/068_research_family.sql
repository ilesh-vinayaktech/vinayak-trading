-- Research families (docs/vti-alignment.md section 3). A family is the unit the multiple-testing correction counts over: every
-- study tests a hypothesis inside one family, the family's trial count only grows, and registering a new study never starts a new
-- family by itself. A new family is an explicit, recorded decision (who, why it is genuinely different). Append-only.
CREATE TABLE research_family (
  family_id     BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE CHECK (name <> ''),
  hypothesis    TEXT NOT NULL CHECK (length(hypothesis) >= 20),
  justification TEXT NOT NULL CHECK (length(justification) >= 20),
  created_by    UUID REFERENCES portal_user(user_id),   -- NULL only for the family made by this migration
  created_at    TIMESTAMPTZ NOT NULL
);
CREATE FUNCTION research_family_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'research_family is append-only: a family is never changed or removed';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER research_family_no_change BEFORE UPDATE OR DELETE ON research_family
  FOR EACH ROW EXECUTE FUNCTION research_family_immutable();

-- Every study registered before families existed shares one family, so their trials carry forward together.
INSERT INTO research_family (name, hypothesis, justification, created_by, created_at) VALUES (
  'Studies registered before research families',
  'Every study registered before research families existed (2026-11-14), counted together.',
  'Created by migration 068: their trials count toward one family so that no multiple-testing penalty is lost.',
  NULL, now()
);

ALTER TABLE experiment ADD COLUMN family_id BIGINT REFERENCES research_family(family_id);
ALTER TABLE experiment DISABLE TRIGGER experiment_lock;
UPDATE experiment SET family_id = (SELECT family_id FROM research_family ORDER BY family_id LIMIT 1);
ALTER TABLE experiment ENABLE TRIGGER experiment_lock;

-- A registered experiment is locked, family included (the only later change is stamping the holdout as opened).
CREATE OR REPLACE FUNCTION experiment_locked() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'a registered experiment cannot be deleted';
  END IF;
  IF (NEW.name, NEW.strategy_id, NEW.hypothesis, NEW.style, NEW.param_ranges, NEW.holdout_start, NEW.holdout_end,
      NEW.registered_at, NEW.study, NEW.study_sha256, NEW.owner_user_id, NEW.family_id)
     IS DISTINCT FROM
     (OLD.name, OLD.strategy_id, OLD.hypothesis, OLD.style, OLD.param_ranges, OLD.holdout_start, OLD.holdout_end,
      OLD.registered_at, OLD.study, OLD.study_sha256, OLD.owner_user_id, OLD.family_id) THEN
    RAISE EXCEPTION 'a registered experiment is locked: register a new one to change it';
  END IF;
  IF OLD.holdout_opened_at IS NOT NULL
     AND (NEW.holdout_opened_at, NEW.holdout_run_id) IS DISTINCT FROM (OLD.holdout_opened_at, OLD.holdout_run_id) THEN
    RAISE EXCEPTION 'the holdout was already opened';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- A backtest study is an experiment with the owner's full settings attached (algo.research.study): the strategy and its
-- grid, the universe, the period and holdout, capital, costs, the thresholds, and the frozen data and cost schedules it was
-- registered against. Once registered it is locked: nothing about it can change or be deleted (a change is a new study, and
-- the trial count goes up). The one change allowed is stamping the holdout as opened, and only once.
ALTER TABLE experiment
  ADD COLUMN study         JSONB,
  ADD COLUMN study_sha256  TEXT,
  ADD COLUMN owner_user_id UUID REFERENCES portal_user(user_id);

CREATE FUNCTION experiment_locked() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'a registered experiment cannot be deleted';
  END IF;
  IF (NEW.name, NEW.strategy_id, NEW.hypothesis, NEW.style, NEW.param_ranges, NEW.holdout_start, NEW.holdout_end,
      NEW.registered_at, NEW.study, NEW.study_sha256, NEW.owner_user_id)
     IS DISTINCT FROM
     (OLD.name, OLD.strategy_id, OLD.hypothesis, OLD.style, OLD.param_ranges, OLD.holdout_start, OLD.holdout_end,
      OLD.registered_at, OLD.study, OLD.study_sha256, OLD.owner_user_id) THEN
    RAISE EXCEPTION 'a registered experiment is locked: register a new one to change it';
  END IF;
  IF OLD.holdout_opened_at IS NOT NULL
     AND (NEW.holdout_opened_at, NEW.holdout_run_id) IS DISTINCT FROM (OLD.holdout_opened_at, OLD.holdout_run_id) THEN
    RAISE EXCEPTION 'the holdout was already opened';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER experiment_lock BEFORE UPDATE OR DELETE ON experiment
  FOR EACH ROW EXECUTE FUNCTION experiment_locked();

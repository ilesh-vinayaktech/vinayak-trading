-- Where a saved strategy stands: RESEARCH, PAPER or LIVE. Append-only: every move is a row with who approved it, when, and
-- (for LIVE) the backtest run that justified it. The current stage is the latest row; no row means RESEARCH.
-- `waived` lists the promotion blockers the owner knowingly accepted (paper entry under the unvalidated-paper waiver).
CREATE TABLE strategy_stage_change (
  change_id        BIGSERIAL PRIMARY KEY,
  config_id        UUID NOT NULL REFERENCES strategy_config(config_id) ON DELETE CASCADE,
  from_stage       TEXT NOT NULL CHECK (from_stage IN ('RESEARCH', 'PAPER', 'LIVE')),
  to_stage         TEXT NOT NULL CHECK (to_stage IN ('RESEARCH', 'PAPER', 'LIVE')),
  approver_user_id UUID NOT NULL REFERENCES portal_user(user_id),
  at               TIMESTAMPTZ NOT NULL,
  run_id           BIGINT REFERENCES backtest_run(run_id),
  reason           TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
  waived           JSONB NOT NULL DEFAULT '[]',
  CHECK (from_stage <> to_stage)
);
CREATE INDEX ON strategy_stage_change (config_id, change_id DESC);

CREATE FUNCTION strategy_stage_change_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
    RETURN OLD;  -- a deleted strategy takes its own history with it
  END IF;
  RAISE EXCEPTION 'strategy stage changes are append-only';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER strategy_stage_change_append_only
  BEFORE UPDATE OR DELETE ON strategy_stage_change
  FOR EACH ROW EXECUTE FUNCTION strategy_stage_change_guard();

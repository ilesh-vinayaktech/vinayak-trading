-- Holdout policy v3 section 7: per candidate, when every lock that can affect a decision was in force (`strategy_locked_at`) and the first forward session that counts.
-- One append-only row per candidate: forward evidence is never appended to the holdout dataset and never counted from before the lock.
CREATE TABLE strategy_lock (
  candidate_id          TEXT PRIMARY KEY CHECK (candidate_id <> ''),   -- 'STRATEGY_ID@version'
  strategy_locked_at    TIMESTAMPTZ NOT NULL,
  forward_evaluation_start DATE NOT NULL,
  definition_sha256     TEXT NOT NULL,
  code_commit           TEXT NOT NULL,
  components            JSONB NOT NULL,
  recorded_at           TIMESTAMPTZ NOT NULL,
  CHECK (forward_evaluation_start > '2026-11-13')
);
CREATE TRIGGER strategy_lock_append_only BEFORE UPDATE OR DELETE ON strategy_lock FOR EACH ROW EXECUTE FUNCTION holdout_append_only();

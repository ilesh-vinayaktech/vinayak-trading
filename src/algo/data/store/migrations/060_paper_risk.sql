-- Risk limits and the kill switch for the paper path. Limits are per account (the mapping algo.risk.limits.Limits loads; NULL = nothing
-- limited). The kill switch is an append-only log of who changed what and why; the mode in force is the latest event per scope
-- (scope NULL = global, otherwise a strategy id), so it survives restarts and every change leaves a record.
ALTER TABLE paper_account ADD COLUMN risk JSONB;

CREATE TABLE kill_switch_event (
  id      BIGSERIAL PRIMARY KEY,
  ts      TIMESTAMPTZ NOT NULL,
  scope   TEXT,
  mode    TEXT NOT NULL CHECK (mode IN ('RUNNING', 'PAUSE', 'CANCEL', 'FLATTEN')),
  by_who  TEXT NOT NULL CHECK (length(btrim(by_who)) > 0),
  reason  TEXT NOT NULL CHECK (length(btrim(reason)) > 0)
);
CREATE FUNCTION kill_switch_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'kill_switch_event is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER kill_switch_event_no_change BEFORE UPDATE OR DELETE ON kill_switch_event
  FOR EACH ROW EXECUTE FUNCTION kill_switch_event_immutable();

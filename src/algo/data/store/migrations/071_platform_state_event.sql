-- The platform state machine's log (docs: TODO 1.2 and 5.3): every transition with when and why. Append-only. A restart always begins
-- at INITIALIZING (the machine's rule), so this log is history and the record of the last boot, not a state to resume from.
CREATE TABLE platform_state_event (
  event_id   BIGSERIAL PRIMARY KEY,
  from_state TEXT NOT NULL,
  to_state   TEXT NOT NULL,
  reason     TEXT NOT NULL,
  operator   BOOLEAN NOT NULL DEFAULT FALSE,
  ts         TIMESTAMPTZ NOT NULL
);
CREATE FUNCTION platform_state_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'platform_state_event is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER platform_state_event_no_change BEFORE UPDATE OR DELETE ON platform_state_event
  FOR EACH ROW EXECUTE FUNCTION platform_state_event_immutable();

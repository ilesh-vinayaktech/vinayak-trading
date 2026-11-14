-- The OMS order log: every transition of every order is one immutable row (spec section 11, event-sourced). An order is only the
-- replay of its rows, so the OMS can restart, a person can read an order's whole history, and nothing can be edited afterwards.
CREATE TABLE oms_event (
  order_id TEXT NOT NULL,
  seq      INT  NOT NULL CHECK (seq >= 0),
  ts       TIMESTAMPTZ NOT NULL,
  state    TEXT,                               -- NULL for a fact that does not move the state (note, cancel request, reconciliation)
  kind     TEXT NOT NULL,
  data     JSONB NOT NULL,                     -- values tagged by algo.sandbox.protocol so Decimals and times come back exact
  PRIMARY KEY (order_id, seq)
);
CREATE INDEX oms_event_ts ON oms_event (ts);
CREATE FUNCTION oms_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'oms_event is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER oms_event_no_change BEFORE UPDATE OR DELETE ON oms_event
  FOR EACH ROW EXECUTE FUNCTION oms_event_immutable();

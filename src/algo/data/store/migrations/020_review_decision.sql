-- Human review decisions captured by the console. Append-only: a changed mind is a new row, the
-- latest row per item wins and the history stays. NOTHING authoritative reads this table: a
-- decision is applied to identity/membership tables by a separate, tested, explicit step.
CREATE TABLE review_decision (
  decision_id    BIGSERIAL PRIMARY KEY,
  item_id        TEXT NOT NULL,
  decision       TEXT NOT NULL,
  effective_date DATE,
  effective_to   DATE,
  evidence_ref   TEXT NOT NULL DEFAULT '',
  note           TEXT NOT NULL DEFAULT '',
  reviewer       TEXT NOT NULL CHECK (length(btrim(reviewer)) > 0),
  decided_at     TIMESTAMPTZ NOT NULL,
  CHECK (effective_to IS NULL OR effective_date IS NULL OR effective_to >= effective_date)
);
CREATE INDEX ON review_decision (item_id, decision_id DESC);

CREATE FUNCTION review_decision_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'review decisions are append-only';
END $$ LANGUAGE plpgsql;

CREATE TRIGGER review_decision_append_only
  BEFORE UPDATE OR DELETE ON review_decision
  FOR EACH ROW EXECUTE FUNCTION review_decision_guard();

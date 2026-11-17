-- Holdout policy v3 section 3 and 4.1: the automatic cutoff snapshot, the provenance statuses and the signed audit.
-- A cutoff snapshot is recorded once, immutably, when a round of definition studies is complete; the batch is frozen later, only after the audit is signed.
CREATE TABLE holdout_cutoff (
  cutoff_id       BIGSERIAL PRIMARY KEY,
  kind            TEXT NOT NULL CHECK (kind IN ('BATCH1', 'QUARTER')),
  due_on          DATE,                -- QUARTER cutoffs: the calendar date; BATCH1: NULL (fires when the round's last study is terminal)
  fired_at        TIMESTAMPTZ NOT NULL,
  snapshot        JSONB NOT NULL,
  snapshot_sha256 TEXT NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  CHECK ((kind = 'BATCH1') = (due_on IS NULL))
);
CREATE UNIQUE INDEX holdout_cutoff_batch1_once ON holdout_cutoff (kind) WHERE kind = 'BATCH1';
CREATE UNIQUE INDEX holdout_cutoff_quarter_once ON holdout_cutoff (due_on) WHERE kind = 'QUARTER';

-- Per candidate: how its independence from holdout-period information stands (section 4). ELIGIBLE needs the signed audit (or a mechanical origin shown);
-- INELIGIBLE has no override (the three MOMENTUM_*, decision D7). Append-only: the newest row of a candidate is its status.
CREATE TABLE holdout_provenance (
  provenance_id BIGSERIAL PRIMARY KEY,
  candidate_id  TEXT NOT NULL CHECK (candidate_id <> ''),   -- 'STRATEGY_ID@version'
  status        TEXT NOT NULL CHECK (status IN ('PROVISIONAL', 'ELIGIBLE', 'INELIGIBLE')),
  reason        TEXT NOT NULL CHECK (reason <> ''),
  recorded_at   TIMESTAMPTZ NOT NULL
);

-- The procedure-provenance audit of section 4.1, signed by the owner. A batch can be frozen only when one exists.
CREATE TABLE holdout_audit (
  audit_id        BIGSERIAL PRIMARY KEY,
  signed_by       TEXT NOT NULL CHECK (signed_by <> ''),
  signed_at       TIMESTAMPTZ NOT NULL,
  document        TEXT NOT NULL CHECK (document <> ''),
  document_sha256 TEXT NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE FUNCTION holdout_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_cutoff_append_only BEFORE UPDATE OR DELETE ON holdout_cutoff FOR EACH ROW EXECUTE FUNCTION holdout_append_only();
CREATE TRIGGER holdout_provenance_append_only BEFORE UPDATE OR DELETE ON holdout_provenance FOR EACH ROW EXECUTE FUNCTION holdout_append_only();
CREATE TRIGGER holdout_audit_append_only BEFORE UPDATE OR DELETE ON holdout_audit FOR EACH ROW EXECUTE FUNCTION holdout_append_only();

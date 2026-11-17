-- A consumed batch's checks that had NO EVIDENCE (e.g. the index lacked a day) can be completed once, later, from the same code and seeds. The original verdicts are never changed;
-- this table is read by the promotion path, which counts a completed check by its later verdict.
CREATE TABLE holdout_supplement (
  batch_id     BIGINT NOT NULL REFERENCES holdout_batch(batch_id),
  candidate_id TEXT NOT NULL CHECK (candidate_id <> ''),
  gate         TEXT NOT NULL CHECK (gate <> ''),
  verdict      TEXT NOT NULL CHECK (verdict IN ('PASS','FAIL')),
  recorded_at  TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (batch_id, candidate_id, gate)
);
CREATE FUNCTION holdout_supplement_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'holdout_supplement is append-only';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM holdout_verdict v JOIN holdout_batch b USING (batch_id)
                 WHERE v.batch_id = NEW.batch_id AND v.candidate_id = NEW.candidate_id AND v.gate = NEW.gate
                   AND v.verdict = 'INSUFFICIENT_EVIDENCE' AND b.state = 'CONSUMED') THEN
    RAISE EXCEPTION 'a supplement completes only a check that had no evidence, in a consumed batch';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER holdout_supplement_guard BEFORE INSERT OR UPDATE OR DELETE ON holdout_supplement
  FOR EACH ROW EXECUTE FUNCTION holdout_supplement_guard();

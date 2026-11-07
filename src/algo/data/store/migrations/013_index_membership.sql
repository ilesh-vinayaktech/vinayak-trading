-- Point-in-time index membership as append-only events (announcement and effective dates kept
-- separate), plus declared coverage: the periods in which the event list is claimed complete.
-- Outside declared+verified coverage membership is UNKNOWN, never "today's list".
CREATE TABLE index_membership_event (
  event_id          BIGSERIAL PRIMARY KEY,
  index_id          TEXT NOT NULL,
  instrument_id     BIGINT NOT NULL REFERENCES instrument,
  symbol_at_event   TEXT NOT NULL,
  event_type        TEXT NOT NULL CHECK (event_type IN ('ADD', 'REMOVE')),
  announcement_date DATE NOT NULL,
  effective_from    DATE NOT NULL,           -- first day the change applies
  source_url        TEXT NOT NULL,
  source_hash       TEXT NOT NULL,
  verified_status   TEXT NOT NULL DEFAULT 'PROVISIONAL'
                    CHECK (verified_status IN ('VERIFIED', 'PROVISIONAL', 'REJECTED')),
  verified_by       TEXT,
  verified_at       TIMESTAMPTZ,
  ingested_at       TIMESTAMPTZ NOT NULL,
  CHECK (effective_from >= announcement_date),
  CHECK (verified_status <> 'VERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)),
  UNIQUE (index_id, instrument_id, event_type, effective_from)
);
CREATE INDEX ON index_membership_event (index_id, effective_from);

-- Only the verification columns may ever change; events are never deleted.
CREATE FUNCTION index_membership_event_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'membership events are append-only';
  END IF;
  IF (OLD.event_id, OLD.index_id, OLD.instrument_id, OLD.symbol_at_event, OLD.event_type,
      OLD.announcement_date, OLD.effective_from, OLD.source_url, OLD.source_hash, OLD.ingested_at)
     IS DISTINCT FROM
     (NEW.event_id, NEW.index_id, NEW.instrument_id, NEW.symbol_at_event, NEW.event_type,
      NEW.announcement_date, NEW.effective_from, NEW.source_url, NEW.source_hash, NEW.ingested_at) THEN
    RAISE EXCEPTION 'membership events are append-only (only verification may change)';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER index_membership_event_append_only
  BEFORE UPDATE OR DELETE ON index_membership_event
  FOR EACH ROW EXECUTE FUNCTION index_membership_event_guard();

CREATE TABLE index_membership_coverage (
  coverage_id     BIGSERIAL PRIMARY KEY,
  index_id        TEXT NOT NULL,
  covered_from    DATE NOT NULL,
  covered_until   DATE,                      -- NULL = up to the present
  basis           TEXT NOT NULL,             -- how completeness was established
  verified_status TEXT NOT NULL DEFAULT 'PROVISIONAL'
                  CHECK (verified_status IN ('VERIFIED', 'PROVISIONAL', 'REJECTED')),
  verified_by     TEXT,
  verified_at     TIMESTAMPTZ,
  declared_at     TIMESTAMPTZ NOT NULL,
  CHECK (covered_until IS NULL OR covered_until >= covered_from),
  CHECK (verified_status <> 'VERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
);

-- Index membership keeps two dates apart and covers constituents that have no tradable instrument.
--  * effective_from is when the change really took effect; announcement_date is when it could have been known; ingested_at is when we
--    recorded it. The old CHECK (effective_from >= announcement_date) forced one date to stand for two questions, so it goes: a strict
--    point-in-time query already filters on announcement_date, a historical one on effective_from.
--  * constituent_key is the stable identity of a member: 'i:<instrument_id>' for an instrument, 'p:<SYMBOL>' for an index placeholder,
--    's:<SYMBOL>' for a symbol with no instrument yet. instrument_id is NULL for those two: member of the index, not tradable.
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'index_membership_event'::regclass
           AND ((contype = 'c' AND pg_get_constraintdef(oid) LIKE '%effective_from >= announcement_date%') OR contype = 'u') LOOP
    EXECUTE format('ALTER TABLE index_membership_event DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

ALTER TABLE index_membership_event ALTER COLUMN instrument_id DROP NOT NULL;
ALTER TABLE index_membership_event ADD COLUMN constituent_key TEXT;
UPDATE index_membership_event SET constituent_key = 'i:' || instrument_id WHERE constituent_key IS NULL;
ALTER TABLE index_membership_event ALTER COLUMN constituent_key SET NOT NULL;
ALTER TABLE index_membership_event ADD CONSTRAINT membership_key_matches_instrument
  CHECK (instrument_id IS NULL OR constituent_key = 'i:' || instrument_id);
ALTER TABLE index_membership_event ADD CONSTRAINT membership_key_has_instrument_or_prefix
  CHECK (instrument_id IS NOT NULL OR constituent_key ~ '^[ps]:.+');
ALTER TABLE index_membership_event ADD CONSTRAINT membership_event_unique
  UNIQUE (index_id, constituent_key, event_type, effective_from);

CREATE OR REPLACE FUNCTION index_membership_event_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'membership events are append-only';
  END IF;
  IF (OLD.event_id, OLD.index_id, OLD.instrument_id, OLD.constituent_key, OLD.symbol_at_event, OLD.event_type,
      OLD.announcement_date, OLD.effective_from, OLD.source_url, OLD.source_hash, OLD.ingested_at)
     IS DISTINCT FROM
     (NEW.event_id, NEW.index_id, NEW.instrument_id, NEW.constituent_key, NEW.symbol_at_event, NEW.event_type,
      NEW.announcement_date, NEW.effective_from, NEW.source_url, NEW.source_hash, NEW.ingested_at) THEN
    RAISE EXCEPTION 'membership events are append-only (only verification may change)';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

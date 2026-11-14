-- The freeze guard (041) refused INSERTs into frozen history but not DELETEs: on 2026-11-14 a routine
-- "delete the last days and reload" removed 2,586 frozen rows and the loader, rightly, would not put them back.
-- Same rule, same explicit switch (SET LOCAL algo.allow_frozen_write = 'on'), now for deletes.
CREATE FUNCTION guard_frozen_bars_delete() RETURNS trigger AS $$
BEGIN
  IF current_setting('algo.allow_frozen_write', true) = 'on' THEN
    RETURN OLD;
  END IF;
  IF EXISTS (
    SELECT 1 FROM data_freeze f JOIN data_freeze_item i USING (freeze_id)
    WHERE f.source = OLD.source AND f.dataset = 'bar_1d' AND i.instrument_id = OLD.instrument_id
      AND OLD.ts < ((f.through_date + 1)::timestamp AT TIME ZONE 'UTC')
  ) THEN
    RAISE EXCEPTION 'bar_1d % history of instrument % is frozen up to its freeze date: not deleted', OLD.source, OLD.instrument_id;
  END IF;
  RETURN OLD;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER bar_1d_frozen_delete_guard BEFORE DELETE ON bar_1d
  FOR EACH ROW EXECUTE FUNCTION guard_frozen_bars_delete();

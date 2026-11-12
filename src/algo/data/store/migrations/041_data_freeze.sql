-- A recorded freeze of a price source's history: "these exact rows, up to this date, are the history we rely on".
-- data_freeze is one snapshot (source, dataset, through date); data_freeze_item holds, per instrument, how many rows it had,
-- the first and last timestamp, and a checksum over every row (timestamp, OHLC, volume, adjusted_through). Both are
-- append-only. `verify` recomputes the checksums, so any later change to frozen history is found and named by stock.
-- Guard: a Kite daily bar for a frozen instrument on or before its freeze date cannot be inserted (it would add to frozen
-- history). A deliberate gap fill sets   SET LOCAL algo.allow_frozen_write = 'on'   in its own transaction.
CREATE TABLE data_freeze (
  freeze_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source          TEXT NOT NULL,
  dataset         TEXT NOT NULL CHECK (dataset IN ('bar_1d')),
  through_date    DATE NOT NULL,
  instruments     INT NOT NULL CHECK (instruments > 0),
  total_rows      BIGINT NOT NULL CHECK (total_rows > 0),
  note            TEXT NOT NULL,
  taken_at        TIMESTAMPTZ NOT NULL,
  UNIQUE (source, dataset, through_date)
);

CREATE TABLE data_freeze_item (
  freeze_id     UUID NOT NULL REFERENCES data_freeze(freeze_id),
  instrument_id BIGINT NOT NULL REFERENCES instrument(instrument_id),
  row_count     INT NOT NULL CHECK (row_count > 0),
  first_ts      TIMESTAMPTZ NOT NULL,
  last_ts       TIMESTAMPTZ NOT NULL,
  sha256        TEXT NOT NULL,
  PRIMARY KEY (freeze_id, instrument_id)
);
CREATE INDEX data_freeze_item_instrument ON data_freeze_item (instrument_id);

CREATE FUNCTION data_freeze_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER data_freeze_no_change BEFORE UPDATE OR DELETE ON data_freeze
  FOR EACH ROW EXECUTE FUNCTION data_freeze_immutable();
CREATE TRIGGER data_freeze_item_no_change BEFORE UPDATE OR DELETE ON data_freeze_item
  FOR EACH ROW EXECUTE FUNCTION data_freeze_immutable();

CREATE FUNCTION guard_frozen_bars() RETURNS trigger AS $$
BEGIN
  IF current_setting('algo.allow_frozen_write', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF EXISTS (
    SELECT 1 FROM data_freeze f JOIN data_freeze_item i USING (freeze_id)
    WHERE f.source = NEW.source AND f.dataset = 'bar_1d' AND i.instrument_id = NEW.instrument_id
      AND NEW.ts < ((f.through_date + 1)::timestamp AT TIME ZONE 'UTC')
  ) THEN
    RAISE EXCEPTION 'bar_1d % history of instrument % is frozen up to its freeze date', NEW.source, NEW.instrument_id;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER bar_1d_frozen_guard BEFORE INSERT ON bar_1d
  FOR EACH ROW EXECUTE FUNCTION guard_frozen_bars();

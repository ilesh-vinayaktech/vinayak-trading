-- Sector of a stock as NSE's index lists state it, dated by the snapshot it came from. Insert-only: a sector change is a new row, never an edit.
CREATE TABLE instrument_sector (
  instrument_id BIGINT NOT NULL REFERENCES instrument(instrument_id),
  sector        TEXT NOT NULL CHECK (length(sector) > 0),
  effective_from DATE NOT NULL,
  source_sha256 TEXT NOT NULL,
  ingested_at   TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (instrument_id, effective_from)
);
CREATE FUNCTION instrument_sector_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'instrument_sector is insert-only: a sector change is a new row';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER instrument_sector_insert_only BEFORE UPDATE OR DELETE ON instrument_sector FOR EACH ROW EXECUTE FUNCTION instrument_sector_insert_only();

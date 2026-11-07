-- A passing gate must point at the exact things it was computed from.
ALTER TABLE validation_report ADD COLUMN refs JSONB NOT NULL DEFAULT '{}';

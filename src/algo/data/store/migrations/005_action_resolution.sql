-- Human decisions for corporate actions the NSE feed cannot price (demerger, rights, arrangement,
-- buy-back ...). Deliberately NOT a column on corporate_action: that table is derived and gets
-- rebuilt from raw JSON, which must never erase a decision. Keyed by (instrument, ex_date, kind).
-- Append-only: the latest row per key wins; earlier rows stay as the audit trail.
CREATE TABLE action_resolution (
  id BIGSERIAL PRIMARY KEY,
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  ex_date DATE NOT NULL,
  kind TEXT NOT NULL,                        -- kind of the review action being resolved
  treatment TEXT NOT NULL CHECK (treatment IN ('factor','ignore')),
  factor NUMERIC CHECK (factor > 0),         -- price multiplier for bars BEFORE ex_date
  method TEXT NOT NULL,                      -- demerger | rights | direct | ignore
  inputs JSONB NOT NULL DEFAULT '{}',        -- what the factor was computed from
  note TEXT NOT NULL,
  resolved_by TEXT NOT NULL,
  resolved_at TIMESTAMPTZ NOT NULL,
  confirmed_by TEXT,                         -- strict (live-trading) reads need this
  confirmed_at TIMESTAMPTZ,
  CHECK ((treatment = 'factor') = (factor IS NOT NULL)),
  CHECK ((confirmed_by IS NULL) = (confirmed_at IS NULL))
);
CREATE INDEX action_resolution_key ON action_resolution (instrument_id, ex_date, kind, id DESC);

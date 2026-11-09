-- Identity dates and corporate-action relationships (design approved before any apply step).
--
-- 1. An archive boundary is NOT a listing date. `instrument.listed_on` stays the verified exchange listing
--    date (NULL until evidenced); the first/last session we hold are separate facts.
-- 2. An alias interval says when a symbol denoted an instrument. Each end says what it rests on, so an
--    archive boundary can never pass as an effective date. Two aliases of one symbol may not overlap.
-- 3. Mergers, amalgamations, relistings, ISIN changes and demergers are effective-dated RELATIONSHIPS
--    between securities, never aliases and never a single `successor` column.
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE instrument
  ADD COLUMN first_observed_on DATE,          -- first session present in our archive
  ADD COLUMN last_traded_on    DATE;          -- last session present in our archive
COMMENT ON COLUMN instrument.listed_on IS 'verified exchange listing date; NULL until evidenced';

ALTER TABLE instrument_alias
  ADD COLUMN valid_from_basis TEXT NOT NULL DEFAULT 'LEGACY_UNSPECIFIED'
      CHECK (valid_from_basis IN ('EVIDENCED', 'FIRST_OBSERVED', 'LEGACY_UNSPECIFIED')),
  ADD COLUMN valid_to_basis TEXT
      CHECK (valid_to_basis IN ('EVIDENCED', 'LAST_OBSERVED')),
  ADD CONSTRAINT instrument_alias_valid_to_basis_needs_valid_to
      CHECK (valid_to_basis IS NULL OR valid_to IS NOT NULL),
  ADD CONSTRAINT instrument_alias_no_overlap
      EXCLUDE USING gist (source WITH =, source_symbol WITH =, daterange(valid_from, valid_to, '[)') WITH &&);

CREATE TABLE corporate_action_relationship (
  relationship_id      BIGSERIAL PRIMARY KEY,
  relationship_type    TEXT NOT NULL CHECK (relationship_type IN
    ('AMALGAMATED_INTO', 'MERGED_INTO', 'SAME_ISSUER_NEW_INSTRUMENT', 'SAME_ISSUER_ISIN_CHANGE', 'DEMERGED_INTO')),
  source_instrument_id BIGINT NOT NULL REFERENCES instrument,
  target_instrument_id BIGINT REFERENCES instrument,     -- NULL while the target is not in the master
  target_symbol        TEXT NOT NULL,                    -- always recorded
  appointed_date       DATE,                             -- the scheme's appointed date, when it has one
  effective_date       DATE NOT NULL,                    -- the date the relationship takes legal / market effect
  last_source_session  DATE,                             -- last session of the source security, when evidenced
  ratio_num            NUMERIC CHECK (ratio_num > 0),    -- target shares per ratio_den source shares
  ratio_den            NUMERIC CHECK (ratio_den > 0),
  known_at             DATE,                             -- when it became public: NOT the effective date
  evidence             JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
  verification_status  TEXT NOT NULL DEFAULT 'PROVISIONAL'
                       CHECK (verification_status IN ('PROVISIONAL', 'VERIFIED', 'REJECTED')),
  review_decision_id   BIGINT NOT NULL,
  recorded_at          TIMESTAMPTZ NOT NULL,
  CHECK ((ratio_num IS NULL) = (ratio_den IS NULL)),
  CHECK (target_instrument_id IS NULL OR target_instrument_id <> source_instrument_id),
  CHECK (appointed_date IS NULL OR appointed_date <= effective_date),
  UNIQUE (relationship_type, source_instrument_id, target_symbol, effective_date)
);

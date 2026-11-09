-- An explicit, reviewed instruction for how a HOLDING converts across an ISIN change. It is NOT inferred from
-- corporate_action_relationship (which only says two ISINs belong to one issuer): the ratio, the
-- effective date and the evidence live here, and the ledger converts only VERIFIED rows.
CREATE TABLE security_conversion (
  conversion_id        BIGSERIAL PRIMARY KEY,
  source_instrument_id BIGINT NOT NULL REFERENCES instrument,
  target_instrument_id BIGINT NOT NULL REFERENCES instrument,
  effective_date       DATE NOT NULL,                -- first day the target holds the position
  last_source_session  DATE,
  ratio_num            NUMERIC NOT NULL CHECK (ratio_num > 0),   -- target shares ...
  ratio_den            NUMERIC NOT NULL CHECK (ratio_den > 0),   -- ... per ratio_den source shares
  relationship_id      BIGINT REFERENCES corporate_action_relationship,
  absorbs_ex_date      DATE,                         -- the corporate action this conversion replaces
  absorbs_kind         TEXT,
  evidence             JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) > 0),
  verification_status  TEXT NOT NULL DEFAULT 'PROVISIONAL'
                       CHECK (verification_status IN ('PROVISIONAL', 'VERIFIED', 'REJECTED')),
  known_at             TIMESTAMPTZ,                  -- when the instruction became public, if known
  review_decision_id   BIGINT,
  recorded_at          TIMESTAMPTZ NOT NULL,
  CHECK (source_instrument_id <> target_instrument_id),
  CHECK ((absorbs_ex_date IS NULL) = (absorbs_kind IS NULL)),
  CHECK (last_source_session IS NULL OR last_source_session < effective_date),
  UNIQUE (source_instrument_id, target_instrument_id, effective_date)
);

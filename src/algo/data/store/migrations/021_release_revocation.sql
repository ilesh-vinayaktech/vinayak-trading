-- A later release can revoke ONE announced change (e.g. "Inclusion revoked" for a single stock in a
-- single index). The announcement and the revocation stay as separate immutable evidence; this row
-- links them, with the authority and its quote. Nothing here edits index_release_row, and no
-- compensating membership transition is invented: the reconstruction cancels the pending change.
CREATE TABLE index_release_revocation (
  revocation_id    BIGSERIAL PRIMARY KEY,
  doc_id           TEXT NOT NULL,            -- the release that announced the change
  component        TEXT NOT NULL,            -- canonical Nifty 200 component
  symbol           TEXT NOT NULL,
  kind             TEXT NOT NULL CHECK (kind IN ('INCLUSION_REVOKED', 'EXCLUSION_REVOKED')),
  effective_from   DATE NOT NULL,            -- the date the revoked change had been announced for
  authority_doc    TEXT NOT NULL,            -- the release that revokes it
  authority_date   DATE NOT NULL,
  authority_quote  TEXT NOT NULL CHECK (length(btrim(authority_quote)) > 0),
  method           TEXT NOT NULL,
  verification     JSONB NOT NULL,
  recorded_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (doc_id, component, symbol, kind, effective_from)
);

-- A demerged entity enters the Nifty indices at zero price under a DUMMY symbol and is replaced by its
-- real listing when that lists. The two stay SEPARATE entities (no alias, no issuer merge); this
-- reviewed, effective-dated record only says that the listing took over the placeholder's index
-- membership on `listed_on`, quoting the release that states it.
CREATE TABLE index_placeholder_replacement (
  replacement_id  BIGSERIAL PRIMARY KEY,
  evidence_doc    TEXT NOT NULL,             -- the exclusion release that names both symbols
  placeholder     TEXT NOT NULL CHECK (placeholder LIKE 'DUMMY%'),
  symbol          TEXT NOT NULL,             -- the real listing
  listed_on       DATE NOT NULL,             -- first day it traded on NSE, per that release
  quote           TEXT NOT NULL CHECK (length(btrim(quote)) > 0),
  method          TEXT NOT NULL,
  verification    JSONB NOT NULL,
  recorded_at     TIMESTAMPTZ NOT NULL,
  UNIQUE (placeholder)
);

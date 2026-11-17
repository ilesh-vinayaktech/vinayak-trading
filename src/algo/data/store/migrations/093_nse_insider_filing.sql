-- NSE moved insider-trading (SEBI PIT) disclosures on 2026-05-03: the old corporates-pit list stopped, the new corporates-pit-gg list
-- carries one row per FILING (company, time, regulation, link to the inline-XBRL file) and the person / quantity / value are inside that file.
-- This table is the filing index; each parsed disclosure becomes a nse_insider_trade row with did = '<app_id>:<context>'.
CREATE TABLE nse_insider_filing (
  app_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  company TEXT,
  regulation TEXT,                     -- Regulation 7 (1) (a) / 7 (2) ...
  submission_type TEXT,                -- Original / Revision
  prev_app_id TEXT,                    -- the filing a revision replaces
  broadcast_at TIMESTAMPTZ,            -- UTC
  ixbrl_url TEXT,
  detail_at TIMESTAMPTZ,               -- when the file was read (NULL = not yet); set even if it could not be parsed
  detail_error TEXT,
  superseded BOOLEAN NOT NULL DEFAULT false,
  ingested_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX nse_insider_filing_pending ON nse_insider_filing (broadcast_at DESC) WHERE detail_at IS NULL AND NOT superseded;

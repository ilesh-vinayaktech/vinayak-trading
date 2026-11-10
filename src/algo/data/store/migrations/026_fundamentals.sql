-- Quarterly financial results (NSE filings). A filing is the unit of evidence: it is never updated, and a
-- restatement is a LATER filing for the same period, so any as-of date can be answered from filed_at.
CREATE TABLE fundamental_filing (
  filing_id     BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  isin          TEXT NOT NULL,
  instrument_id BIGINT REFERENCES instrument(instrument_id),   -- NULL when the ISIN is not in the master
  seq_number    TEXT NOT NULL,                                 -- NSE's id of the filing
  period_start  DATE NOT NULL,
  period_end    DATE NOT NULL,
  basis         TEXT NOT NULL CHECK (basis IN ('STANDALONE','CONSOLIDATED')),
  audited       BOOLEAN NOT NULL,
  bank          BOOLEAN NOT NULL,
  filed_at      TIMESTAMPTZ NOT NULL,                          -- NSE broadcast time: nothing may be used before it
  rounding      TEXT NOT NULL,                                 -- as printed (Crores / Lakhs); values are stored in rupees
  xbrl_url      TEXT NOT NULL,
  raw_sha256    TEXT NOT NULL,                                 -- the stored XBRL file in the lake
  ingested_at   TIMESTAMPTZ NOT NULL,
  UNIQUE (symbol, seq_number),
  CHECK (period_end > period_start)
);
CREATE INDEX fundamental_filing_period ON fundamental_filing (symbol, basis, period_end);

CREATE TABLE fundamental_fact (
  filing_id BIGINT NOT NULL REFERENCES fundamental_filing(filing_id),
  metric    TEXT NOT NULL,
  scope     TEXT NOT NULL CHECK (scope IN ('QUARTER','YTD')),
  value     NUMERIC NOT NULL,
  PRIMARY KEY (filing_id, metric, scope)
);

-- Filings NSE lists that could not be loaded, with the reason, so coverage gaps are explicit.
CREATE TABLE fundamental_unloaded (
  symbol      TEXT NOT NULL,
  seq_number  TEXT NOT NULL,
  period_end  DATE NOT NULL,
  basis       TEXT NOT NULL,
  filed_at    TIMESTAMPTZ NOT NULL,
  reason      TEXT NOT NULL,                                   -- NO_XBRL_OLD_FORMAT | FETCH_FAILED | UNPARSEABLE | NOT_QUARTERLY
  detail      TEXT NOT NULL DEFAULT '',
  detail_url  TEXT,
  noted_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (symbol, seq_number)
);

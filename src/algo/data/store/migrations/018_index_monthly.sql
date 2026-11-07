-- Official month-end constituents per index (NSE Indices monthly 'Market Capitalisation & Weightage'
-- archive). These are SNAPSHOTS (a stock present at month-end was not necessarily present all month),
-- kept apart from press-release events and from derived membership intervals.
CREATE TABLE index_monthly_snapshot (
  snapshot_id    BIGSERIAL PRIMARY KEY,
  index_name     TEXT NOT NULL,              -- as printed in the PDF title
  component      TEXT,                       -- canonical Nifty 200 component / NIFTY_100 / NIFTY_200
  as_of          DATE NOT NULL,              -- the report date printed in the PDF
  zip_hash       TEXT NOT NULL,              -- sha256 of the original archive
  pdf_name       TEXT NOT NULL,
  pdf_hash       TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  problems       JSONB NOT NULL,             -- anything the parser could not make sense of
  parsed_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (index_name, as_of, parser_version)
);

CREATE TABLE index_monthly_constituent (
  snapshot_id    BIGINT NOT NULL REFERENCES index_monthly_snapshot ON DELETE RESTRICT,
  symbol         TEXT NOT NULL,
  name           TEXT NOT NULL,
  industry       TEXT NOT NULL,
  price          NUMERIC NOT NULL,
  index_mcap     NUMERIC NOT NULL,
  weight         NUMERIC NOT NULL,
  page           INT NOT NULL,
  instrument_id  BIGINT REFERENCES instrument,
  mapping_status TEXT NOT NULL CHECK (mapping_status IN ('MAPPED', 'UNMAPPED_SYMBOL')),
  PRIMARY KEY (snapshot_id, symbol)
);

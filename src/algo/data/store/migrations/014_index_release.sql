-- Parsed NSE Indices press releases: PROVISIONAL evidence rows with full provenance. They are never
-- membership data; a later derivation stage turns reviewed rows into index_membership_event.
CREATE TABLE index_release_document (
  doc_id         TEXT NOT NULL,              -- lake dataset name, e.g. pr_ind_prs10062020
  parser_version TEXT NOT NULL,
  announced      DATE NOT NULL,
  source_url     TEXT NOT NULL,
  source_hash    TEXT NOT NULL,              -- sha256 of the stored original
  kind           TEXT NOT NULL,              -- REPLACEMENT_TABLES | COMPANY_NOTICE | MANUAL_REVIEW
  sections       JSONB NOT NULL,
  notes          JSONB NOT NULL,
  parsed_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (doc_id, parser_version)
);

CREATE TABLE index_release_row (
  row_id         BIGSERIAL PRIMARY KEY,
  doc_id         TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  page           INT NOT NULL,
  section_no     INT NOT NULL,
  section_name   TEXT NOT NULL,
  component      TEXT,                       -- canonical Nifty 200 component, NULL = not one
  action         TEXT NOT NULL CHECK (action IN ('EXCLUDED', 'INCLUDED')),
  symbol         TEXT NOT NULL,
  company        TEXT NOT NULL,
  effective_from DATE,
  related_symbol TEXT,
  raw_text       TEXT NOT NULL,
  instrument_id  BIGINT REFERENCES instrument,
  mapping_status TEXT NOT NULL CHECK (mapping_status IN
    ('MAPPED', 'UNMAPPED_SYMBOL', 'PLACEHOLDER_SECURITY')),
  review_status  TEXT NOT NULL DEFAULT 'PROVISIONAL'
                 CHECK (review_status IN ('VERIFIED', 'PROVISIONAL', 'REJECTED')),
  FOREIGN KEY (doc_id, parser_version) REFERENCES index_release_document,
  UNIQUE (doc_id, parser_version, page, section_no, action, symbol)
);

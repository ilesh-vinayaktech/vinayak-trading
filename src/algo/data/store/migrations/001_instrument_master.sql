CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE exchange (
  exchange_id SERIAL PRIMARY KEY,
  mic TEXT NOT NULL UNIQUE,
  country TEXT NOT NULL,
  timezone TEXT NOT NULL,
  currency TEXT NOT NULL,
  calendar_id TEXT NOT NULL
);

CREATE TABLE instrument (
  instrument_id BIGSERIAL PRIMARY KEY,
  asset_class TEXT NOT NULL CHECK (asset_class IN
    ('equity','etf','index','future','option','fx','crypto_spot','crypto_perp','macro_series')),
  exchange_id INT NOT NULL REFERENCES exchange,
  symbol TEXT NOT NULL,
  isin TEXT,
  name TEXT,
  quote_currency TEXT NOT NULL,
  listed_on DATE,
  delisted_on DATE,          -- never delete instruments; set this instead
  status TEXT NOT NULL DEFAULT 'active',
  meta JSONB NOT NULL DEFAULT '{}',
  CHECK (delisted_on IS NULL OR listed_on IS NULL OR delisted_on >= listed_on)
);

-- Historical contract terms: lot/tick/step can change over time.
CREATE TABLE instrument_terms (
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  valid_from DATE NOT NULL,
  valid_to DATE,             -- exclusive; NULL = open ended
  lot_size NUMERIC NOT NULL CHECK (lot_size > 0),
  tick_size NUMERIC NOT NULL CHECK (tick_size > 0),
  qty_step NUMERIC NOT NULL CHECK (qty_step > 0),
  multiplier NUMERIC NOT NULL DEFAULT 1 CHECK (multiplier > 0),
  margin_rule_version TEXT,
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  EXCLUDE USING gist (instrument_id WITH =, daterange(valid_from, valid_to, '[)') WITH &&)
);

CREATE TABLE instrument_alias (
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  source TEXT NOT NULL,
  source_symbol TEXT NOT NULL,
  source_token TEXT,
  valid_from DATE NOT NULL,
  valid_to DATE,
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  EXCLUDE USING gist (source WITH =, source_symbol WITH =,
                      daterange(valid_from, valid_to, '[)') WITH &&)
);

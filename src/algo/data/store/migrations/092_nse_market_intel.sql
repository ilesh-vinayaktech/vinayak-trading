-- NSE market intelligence: bulk/block deals, insider (SEBI PIT) trades, shareholding pattern headline, FII/DII cash flows.
-- Keyed by NSE symbol text (no instrument FK: NSE symbols are reused and renamed; join on symbol at read time).
-- Delivery % and most-active are NOT tables: they are derived from bar_1d (algo.data.nse_intel).
-- Every insert is ON CONFLICT DO NOTHING, so an hourly re-poll of an overlapping window is free.
CREATE TABLE nse_bulk_block_deal (
  kind TEXT NOT NULL CHECK (kind IN ('bulk', 'block')),
  trade_date DATE NOT NULL,
  symbol TEXT NOT NULL,
  client TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  quantity NUMERIC NOT NULL,
  price NUMERIC NOT NULL,
  remarks TEXT,
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (kind, trade_date, symbol, client, side, quantity, price)
);
CREATE INDEX nse_bulk_block_symbol ON nse_bulk_block_deal (symbol, trade_date DESC);

CREATE TABLE nse_insider_trade (
  did TEXT PRIMARY KEY,                -- NSE's own row id
  symbol TEXT NOT NULL,
  person TEXT NOT NULL,
  person_category TEXT,
  transaction_type TEXT,               -- Buy / Sell / Pledge / Revoke ...
  acquisition_mode TEXT,
  security_type TEXT,
  quantity NUMERIC,
  value NUMERIC,
  shares_before NUMERIC, pct_before NUMERIC,
  shares_after NUMERIC, pct_after NUMERIC,
  from_date DATE, to_date DATE,
  intimation_date DATE,
  broadcast_at TIMESTAMPTZ,            -- UTC (NSE publishes Indian time)
  xbrl_url TEXT,
  ingested_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX nse_insider_symbol ON nse_insider_trade (symbol, broadcast_at DESC);
CREATE INDEX nse_insider_broadcast ON nse_insider_trade (broadcast_at DESC);

CREATE TABLE nse_shareholding (
  record_id TEXT PRIMARY KEY,          -- NSE's id; a revision arrives as a new record
  symbol TEXT NOT NULL,
  isin TEXT,
  period_end DATE NOT NULL,
  promoter_pct NUMERIC,
  public_pct NUMERIC,
  employee_trust_pct NUMERIC,
  submitted_on DATE,
  broadcast_at TIMESTAMPTZ,            -- UTC
  revised BOOLEAN NOT NULL DEFAULT false,
  xbrl_url TEXT,                       -- the full breakdown lives in this file; the columns below are read from it
  fii_pct NUMERIC,                     -- foreign institutions (FPI + FDI), % of shares
  dii_pct NUMERIC,                     -- domestic institutions (mutual funds, insurers, banks, pension funds ...)
  mf_pct NUMERIC,                      -- mutual funds / UTI, a part of dii_pct
  insurance_pct NUMERIC,               -- insurance companies, a part of dii_pct
  retail_pct NUMERIC,                  -- resident individuals up to Rs 2 lakh nominal capital
  split_at TIMESTAMPTZ,                -- when the XBRL was read (NULL = not yet); set even when it could not be parsed
  split_error TEXT,
  ingested_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX nse_shareholding_symbol ON nse_shareholding (symbol, period_end DESC);

CREATE TABLE nse_fii_dii (
  trade_date DATE NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('FII', 'DII')),
  buy_value NUMERIC NOT NULL,          -- Rs crore, cash market
  sell_value NUMERIC NOT NULL,
  net_value NUMERIC NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (trade_date, category)
);

-- AMFI's half-yearly market-cap ranking (algo.data.amfi_caps), one list per period, each company matched to our instrument
-- where we can (by ISIN, else by the NSE symbol it had on the period end). A list is relied on from effective_from (the
-- first day of the second month after its period), so a backtest never knows a list before it was published.
-- segment: large 1-100, mid 101-250, small 251-500, micro 501+ (micro is our definition; AMFI calls all of 251+ small).
CREATE TABLE market_cap_list (
  period_end     DATE PRIMARY KEY,
  effective_from DATE NOT NULL,
  companies      INT NOT NULL,
  matched        INT NOT NULL,
  source_url     TEXT NOT NULL,
  raw_sha256     TEXT NOT NULL,
  loaded_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE market_cap_rank (
  period_end    DATE NOT NULL REFERENCES market_cap_list(period_end),
  position      INT NOT NULL,          -- order in the file (equal caps share a rank, so rank alone is not unique)
  rank          INT NOT NULL,
  isin          TEXT,
  nse_symbol    TEXT,
  name          TEXT NOT NULL,
  avg_cap       NUMERIC NOT NULL,      -- six-month average full market cap, Rs crore
  segment       TEXT NOT NULL CHECK (segment IN ('large', 'mid', 'small', 'micro')),
  instrument_id BIGINT REFERENCES instrument(instrument_id),
  PRIMARY KEY (period_end, position)
);
CREATE INDEX market_cap_rank_instrument ON market_cap_rank (instrument_id, period_end);

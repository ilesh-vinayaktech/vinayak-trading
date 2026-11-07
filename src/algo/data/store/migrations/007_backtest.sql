-- Every backtest records exactly which data and rules produced it, so it can be reproduced and so
-- a research-mode result can never be mistaken for strict-mode evidence.
CREATE TABLE backtest_run (
  run_id BIGSERIAL PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  params JSONB NOT NULL,
  params_hash TEXT NOT NULL,
  code_version TEXT NOT NULL,
  reader_mode TEXT NOT NULL CHECK (reader_mode IN ('research','strict')),
  config JSONB NOT NULL,
  cost_model JSONB NOT NULL,
  adjustment_versions JSONB NOT NULL,   -- instrument_id -> reader adjustment_version
  provisional_events JSONB NOT NULL,    -- estimates applied (research only)
  unapplied_events JSONB NOT NULL,      -- unpriced actions affecting prices (reported separately)
  blocked_instruments JSONB NOT NULL,   -- instrument_id -> why it was excluded
  unmodelled_events JSONB NOT NULL,     -- held through an action the accounting cannot model
  accounting_complete BOOLEAN NOT NULL,
  dividends_received NUMERIC NOT NULL,
  metrics JSONB NOT NULL,
  result_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE backtest_trade (
  run_id BIGINT NOT NULL REFERENCES backtest_run,
  seq INT NOT NULL,
  day DATE NOT NULL,
  instrument_id BIGINT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  qty NUMERIC NOT NULL, price NUMERIC NOT NULL, cost NUMERIC NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE backtest_equity (
  run_id BIGINT NOT NULL REFERENCES backtest_run,
  day DATE NOT NULL,
  equity NUMERIC NOT NULL,
  PRIMARY KEY (run_id, day)
);

-- The financial ledger of each backtest: the canonical record of every cash, position, fee and P&L
-- movement, each citing its source event (`ref`). Dashboards and reports must read P&L from here
-- (or the view below), never recompute it independently.
CREATE TABLE backtest_ledger (
  run_id BIGINT NOT NULL REFERENCES backtest_run,
  seq INT NOT NULL,
  day DATE NOT NULL,
  ledger TEXT NOT NULL CHECK (ledger IN ('cash','position','fee','pnl','event')),
  kind TEXT NOT NULL,
  instrument_id BIGINT,
  qty NUMERIC NOT NULL,       -- share delta (position) / shares held (dividend, event)
  amount NUMERIC NOT NULL,    -- cash delta | cost-basis delta | fee | realized P&L
  ref TEXT NOT NULL,          -- source event: trade:<n> | action:<instrument>:<ex_date>:<kind>:<n>
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX backtest_ledger_ref ON backtest_ledger (run_id, ref);

ALTER TABLE backtest_run
  ADD COLUMN ledger_reconciled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN reconciliation JSONB NOT NULL DEFAULT '[]',   -- problems found by Ledger.reconcile()
  ADD COLUMN pnl JSONB NOT NULL DEFAULT '{}';              -- realized/unrealized/dividends/fees/net

-- The ONE definition of the P&L components that come from entries (unrealized needs prices).
CREATE VIEW backtest_ledger_pnl AS
SELECT run_id,
  COALESCE(SUM(amount) FILTER (WHERE ledger = 'pnl' AND kind = 'REALIZED'), 0) AS realized,
  COALESCE(SUM(amount) FILTER (WHERE ledger = 'cash' AND kind = 'DIVIDEND'), 0) AS dividends,
  COALESCE(SUM(amount) FILTER (WHERE ledger = 'fee'), 0) AS fees,
  COALESCE(SUM(amount) FILTER (WHERE ledger = 'cash'), 0) AS cash_balance
FROM backtest_ledger GROUP BY run_id;

-- Every simulated trade can explain every rupee deducted from it: the itemised charge lines
-- (basis value, rate/formula, rounding, source key) plus the exact schedule id / version / status.
ALTER TABLE backtest_trade
  ADD COLUMN slippage_bps NUMERIC NOT NULL DEFAULT 0,
  ADD COLUMN charges JSONB NOT NULL DEFAULT '{}';

-- Fees by type, straight from the ledger (the only sanctioned source for reported costs).
CREATE VIEW backtest_ledger_fees AS
SELECT run_id, kind AS fee_type, SUM(amount) AS amount
FROM backtest_ledger WHERE ledger = 'fee' GROUP BY run_id, kind;

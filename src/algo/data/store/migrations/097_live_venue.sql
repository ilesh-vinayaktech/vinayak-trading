-- One pipeline for paper and live accounts: the account's mode says where its orders go (PAPER: the simulated broker and simulated fills;
-- LIVE: the real broker, filled by what the broker reports). Everything else (proposals, approval, risk, the event book, the OMS log) is shared.
-- Opening a LIVE account does not by itself allow live trading: the live gate (execution/live_gate.py) still has to be open for every order.
ALTER TABLE paper_account DROP CONSTRAINT paper_account_mode_check;
ALTER TABLE paper_account ADD CONSTRAINT paper_account_mode_check CHECK (mode IN ('PAPER', 'LIVE'));

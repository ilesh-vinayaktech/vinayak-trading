-- Progress inside a running job (days done of the backtest being run), so the page can show real progress and a time left.
ALTER TABLE study_run ADD COLUMN step_done INT NOT NULL DEFAULT 0;
ALTER TABLE study_run ADD COLUMN step_total INT NOT NULL DEFAULT 0;
-- A short name for a run that is not an ordinary one (for example "double costs" or "triple capital" in a verdict), so the
-- Backtests list does not show it as if it were a trial.
ALTER TABLE backtest_run ADD COLUMN label TEXT;

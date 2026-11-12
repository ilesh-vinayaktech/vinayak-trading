-- A study's queue now carries two kinds of job: the trials (every parameter combination through the engine) and the
-- verdict (walk-forward, deflated Sharpe and the other gates over the finished trials). Still one active job per study.
ALTER TABLE study_run ADD COLUMN kind TEXT NOT NULL DEFAULT 'trials' CHECK (kind IN ('trials', 'verdict'));

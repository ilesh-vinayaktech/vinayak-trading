-- The holdout: the final, one-time test of a study's chosen settings on days the study never saw. One row per study, ever
-- (the primary key is the "opened once" rule; experiment.holdout_opened_at is claimed in the same transaction).
ALTER TABLE study_run DROP CONSTRAINT study_run_kind_check;
ALTER TABLE study_run ADD CONSTRAINT study_run_kind_check CHECK (kind IN ('trials', 'verdict', 'holdout'));

CREATE TABLE study_holdout (
  experiment_id BIGINT PRIMARY KEY REFERENCES experiment(experiment_id),
  run_id        BIGINT NOT NULL REFERENCES backtest_run(run_id),
  passed        BOOLEAN NOT NULL,
  evidence      JSONB NOT NULL,
  gates         JSONB NOT NULL,
  refs          JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL
);

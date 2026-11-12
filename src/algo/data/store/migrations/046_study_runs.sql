-- Running a registered study (algo.research.study_runner): a job per request (only one active per study) and one row per
-- trial (a parameter combination run over the study's research window). The trial's daily returns are kept so the validation
-- steps (walk-forward, deflated Sharpe, overfitting) can be computed from them without running the engine again.
CREATE TABLE study_run (
  run_id        BIGSERIAL PRIMARY KEY,
  experiment_id BIGINT NOT NULL REFERENCES experiment(experiment_id),
  status        TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED')),
  total         INT NOT NULL DEFAULT 0,
  done          INT NOT NULL DEFAULT 0,
  current       TEXT,
  error         TEXT,
  detail        JSONB,                       -- e.g. the universe coverage per AMFI list
  requested_by  UUID REFERENCES portal_user(user_id),
  created_at    TIMESTAMPTZ NOT NULL,
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);
CREATE UNIQUE INDEX study_run_one_active ON study_run (experiment_id) WHERE status IN ('QUEUED', 'RUNNING');

CREATE TABLE study_trial (
  trial_id      BIGSERIAL PRIMARY KEY,
  experiment_id BIGINT NOT NULL REFERENCES experiment(experiment_id),
  variant       TEXT NOT NULL CHECK (variant IN ('base')),
  params        JSONB NOT NULL,
  params_hash   TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('DONE', 'FAILED')),
  metrics       JSONB,
  returns       JSONB,                       -- the daily returns of the run, oldest first
  backtest_run  BIGINT REFERENCES backtest_run(run_id),
  error         TEXT,
  seconds       DOUBLE PRECISION,
  finished_at   TIMESTAMPTZ NOT NULL,
  UNIQUE (experiment_id, params_hash, variant)
);

-- Pre-registration, the trial counter and validation reports. The counter is what makes the
-- Deflated Sharpe honest: N = every distinct configuration ever tried under an experiment.
CREATE TABLE experiment (
  experiment_id    BIGSERIAL PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE,
  strategy_id      TEXT NOT NULL,
  hypothesis       TEXT NOT NULL CHECK (length(btrim(hypothesis)) > 0),
  style            TEXT NOT NULL CHECK (style IN ('long_only', 'market_neutral')),
  param_ranges     JSONB NOT NULL,            -- {"lookback": [60, 250], ...} registered BEFORE trials
  holdout_start    DATE NOT NULL,
  holdout_end      DATE NOT NULL CHECK (holdout_end >= holdout_start),
  registered_at    TIMESTAMPTZ NOT NULL,
  holdout_opened_at TIMESTAMPTZ,              -- set once; the holdout can never be reopened
  holdout_run_id   BIGINT REFERENCES backtest_run(run_id)
);

CREATE TABLE experiment_trial (
  trial_id      BIGSERIAL PRIMARY KEY,
  experiment_id BIGINT NOT NULL REFERENCES experiment(experiment_id),
  params        JSONB NOT NULL,
  params_hash   TEXT NOT NULL,
  sharpe        DOUBLE PRECISION,             -- per-period Sharpe of the trial (NULL = undefined)
  run_id        BIGINT REFERENCES backtest_run(run_id),
  recorded_at   TIMESTAMPTZ NOT NULL,
  UNIQUE (experiment_id, params_hash)
);

CREATE TABLE validation_report (
  report_id         BIGSERIAL PRIMARY KEY,
  experiment_id     BIGINT NOT NULL REFERENCES experiment(experiment_id),
  run_id            BIGINT NOT NULL REFERENCES backtest_run(run_id),
  passed            BOOLEAN NOT NULL,
  thresholds_status TEXT NOT NULL,            -- only 'confirmed' thresholds can promote
  n_trials          INTEGER NOT NULL,
  evidence          JSONB NOT NULL,
  gates             JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL
);

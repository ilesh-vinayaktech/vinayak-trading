-- How each scheduled job's runs ended, so the portal can show when everything last synced.
-- One row per run (scripts/run_job.py writes it); only the most recent few per job are kept.
CREATE TABLE job_run (
  run_id      BIGSERIAL PRIMARY KEY,
  job         TEXT NOT NULL,
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'skipped')),
  attempts    INT NOT NULL CHECK (attempts >= 0),
  detail      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX job_run_job_started ON job_run (job, started_at DESC);

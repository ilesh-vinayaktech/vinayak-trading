-- Live progress of long jobs (feature validation, feature computation, alpha discovery), so the console can show what a running job is doing.
-- Unlike the registries this table is deliberately MUTABLE: a row is updated while its job runs and holds only the latest state. It is not evidence of anything.
-- `pid` lets a reader notice a job whose process has gone without finishing.
CREATE TABLE job_progress (
  run_id      BIGSERIAL PRIMARY KEY,
  job         TEXT NOT NULL CHECK (length(btrim(job)) > 0),
  label       TEXT NOT NULL,
  pid         INTEGER NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('RUNNING', 'DONE', 'FAILED')),
  done        INTEGER NOT NULL DEFAULT 0 CHECK (done >= 0),
  total       INTEGER NOT NULL CHECK (total >= 1),
  phase       TEXT NOT NULL DEFAULT '',
  message     TEXT NOT NULL DEFAULT '',
  started_at  TIMESTAMPTZ NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  CHECK ((status = 'RUNNING') = (finished_at IS NULL)),
  CHECK (done <= total)
);
CREATE INDEX job_progress_recent ON job_progress (started_at DESC);

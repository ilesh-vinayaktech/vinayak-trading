-- Timing columns for job_progress so the console can estimate time remaining from how long finished steps actually took.
-- first_done_at / last_done_at: when the first and the most recent step were completed (NULL until a step completes).
-- uniform: whether the job's steps are roughly equal in size; an estimate from the average step is only meaningful when they are.
ALTER TABLE job_progress
  ADD COLUMN first_done_at TIMESTAMPTZ,
  ADD COLUMN last_done_at  TIMESTAMPTZ,
  ADD COLUMN uniform       BOOLEAN NOT NULL DEFAULT TRUE;

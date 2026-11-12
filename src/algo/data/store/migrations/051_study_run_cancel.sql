-- Asking a job that has already started to stop. The worker looks at this flag as it works and ends the job cleanly
-- (CANCELLED); trials already finished are kept.
ALTER TABLE study_run ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT false;

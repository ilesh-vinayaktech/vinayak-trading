-- A study run can be asked to carry on by itself: when it finishes, the next stage (verdict, then the inner holdout if the verdict passed) is queued without a click.
ALTER TABLE study_run ADD COLUMN chain BOOLEAN NOT NULL DEFAULT FALSE;

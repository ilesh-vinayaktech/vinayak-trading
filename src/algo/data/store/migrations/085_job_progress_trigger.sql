-- Step timing that does not depend on the client: when a job's `done` count rises and the client did not set last_done_at itself, the database stamps it.
-- first_done_count is the `done` value at the first observed completion, so the average step time is (last - first) / (done - first_done_count): correct whether the first
-- observation was step 1 (a client that sets timing itself) or a later step (a client that predates the timing columns).
ALTER TABLE job_progress ADD COLUMN first_done_count INTEGER;
-- rows written by clients that set timing themselves before this column existed started at one finished step
UPDATE job_progress SET first_done_count = 1 WHERE first_done_at IS NOT NULL;

CREATE FUNCTION job_progress_stamp() RETURNS trigger AS $$
BEGIN
  IF NEW.done > OLD.done AND NEW.last_done_at IS NOT DISTINCT FROM OLD.last_done_at THEN
    NEW.last_done_at := now();
    IF NEW.first_done_at IS NULL THEN
      NEW.first_done_at := NEW.last_done_at;
    END IF;
  END IF;
  IF NEW.first_done_at IS NOT NULL AND NEW.first_done_count IS NULL THEN
    NEW.first_done_count := NEW.done;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER job_progress_stamp BEFORE UPDATE ON job_progress FOR EACH ROW EXECUTE FUNCTION job_progress_stamp();

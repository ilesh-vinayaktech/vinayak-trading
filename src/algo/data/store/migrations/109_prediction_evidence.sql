-- What each prediction saw, kept with it so it can be rebuilt and audited: when it was made, the feature values as the model saw them (null where a figure was
-- missing) and the last day its model had learned from. A live prediction is written once and never replaced; earlier rows have none of these.
ALTER TABLE prediction_log
  ADD COLUMN made_at       TIMESTAMPTZ,
  ADD COLUMN features      JSONB,
  ADD COLUMN train_through DATE;

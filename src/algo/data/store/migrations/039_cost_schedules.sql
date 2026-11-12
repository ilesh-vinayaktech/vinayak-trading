-- Trading-cost schedules per broker, managed in the portal. `doc` is the full schedule document in the same shape as
-- config/cost_schedules/*.json (components, each citing a source with url, document hash and a literal quote), so the same
-- validator (schedule_from_dict) and calculator are used; the other columns are what the screens filter and show.
-- status: verified (a named person checked it against the cited sources), extracted_unverified (read from the documents,
-- not yet checked), assumed_backfill (a current rate extended into a period it is not evidenced for; flagged on every run).
CREATE TABLE cost_schedule (
  schedule_id TEXT NOT NULL,
  version     TEXT NOT NULL,
  broker      TEXT NOT NULL,
  product     TEXT NOT NULL CHECK (product IN ('DELIVERY', 'INTRADAY')),
  valid_from  DATE NOT NULL,
  valid_until DATE,                         -- inclusive; NULL = still in force
  status      TEXT NOT NULL CHECK (status IN ('verified', 'extracted_unverified', 'assumed_backfill')),
  verified_by TEXT,
  verified_at TIMESTAMPTZ,
  doc         JSONB NOT NULL,
  doc_hash    TEXT NOT NULL,
  created_by  UUID REFERENCES portal_user(user_id),
  created_at  TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (schedule_id, version),
  CHECK (valid_until IS NULL OR valid_until >= valid_from),
  CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL))
);
CREATE INDEX cost_schedule_lookup ON cost_schedule (broker, product, valid_from);

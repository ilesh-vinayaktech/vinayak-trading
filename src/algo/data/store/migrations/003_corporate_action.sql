-- Corporate actions, kept apart from raw bars (bars are never adjusted in place).
-- knowledge_time = when a backtest may first use the action. NSE's feed has no announcement date
-- (caBroadcastDate is null), so the default is a conservative proxy: start of ex-date (IST).
CREATE TABLE corporate_action (
  id BIGSERIAL PRIMARY KEY,
  instrument_id BIGINT NOT NULL REFERENCES instrument,
  ex_date DATE NOT NULL,
  record_date DATE,
  kind TEXT NOT NULL,                       -- bonus | split | dividend | rights | demerger | ...
  status TEXT NOT NULL CHECK (status IN ('ok','review')),
  num NUMERIC, den NUMERIC, amount NUMERIC,  -- share multiplier num/den; cash per share
  reason TEXT NOT NULL DEFAULT '',          -- why it is in review
  subject TEXT NOT NULL,                    -- the raw NSE text
  announced_at TIMESTAMPTZ,                 -- NULL until a real announcement feed exists
  knowledge_time TIMESTAMPTZ NOT NULL,
  knowledge_time_source TEXT NOT NULL,
  source TEXT NOT NULL,
  raw_checksum TEXT NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL
);
-- identical economics on the same day are one action (dedupes repeated NSE rows / re-fetches)
CREATE UNIQUE INDEX corporate_action_identity ON corporate_action
  (instrument_id, ex_date, kind, status, COALESCE(num,-1), COALESCE(den,-1), COALESCE(amount,-1));
CREATE INDEX corporate_action_by_instrument ON corporate_action (instrument_id, ex_date);

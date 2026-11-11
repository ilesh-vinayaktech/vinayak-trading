-- Exceptions to the regular Mon-Fri 09:15-15:30 IST session, for the live feed and the portal's trading calendar.
-- SESSION: the exact trading window(s) of that date (a Muhurat evening, a Saturday special session, a drill). When a date
--          has any, they REPLACE the regular rule and any CLOSED entry for the date (NSE lists the Muhurat day as a holiday).
-- CLOSED:  no trading that date (an exchange holiday). One per date.
-- A date with no rows follows the rule. Times are exchange wall-clock (IST). `source` says where it came from: 'nse'
-- (the holiday list sync) or 'manual' (someone added it on the portal).
CREATE TABLE market_session (
  session_id   BIGSERIAL PRIMARY KEY,
  session_date DATE NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('SESSION', 'CLOSED')),
  start_time   TIME,
  end_time     TIME,
  note         TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 300),
  source       TEXT NOT NULL CHECK (source IN ('nse', 'manual')),
  created_by   UUID REFERENCES portal_user(user_id),
  created_at   TIMESTAMPTZ NOT NULL,
  CHECK (
    (kind = 'SESSION' AND start_time IS NOT NULL AND end_time IS NOT NULL AND start_time < end_time)
    OR (kind = 'CLOSED' AND start_time IS NULL AND end_time IS NULL)
  )
);
CREATE UNIQUE INDEX market_session_one_closed_per_day ON market_session (session_date) WHERE kind = 'CLOSED';
CREATE INDEX market_session_date ON market_session (session_date);

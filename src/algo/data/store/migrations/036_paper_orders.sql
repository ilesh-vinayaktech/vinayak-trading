-- Paper trading, continued (UNVALIDATED research, see 035): the strategy's proposals and what happened to them.
-- paper_run:    one row per user and decision day (the runner is idempotent on it); `detail` keeps the strategy's audit.
-- paper_order:  a proposed order waiting for its owner. PENDING -> APPROVED -> FILLED, or REJECTED / EXPIRED / FAILED.
--               Nothing is booked in paper_event until the order is FILLED.
-- paper_equity: end-of-day value of each account, written by the runner.
CREATE TABLE paper_run (
  run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES paper_account(user_id),
  decision_day     DATE NOT NULL,
  strategy_id      TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  params_hash      TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('PROPOSED', 'NO_CHANGE', 'SKIPPED', 'ERROR')),
  detail           JSONB NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, decision_day)
);

CREATE TABLE paper_order (
  order_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES paper_account(user_id),
  decision_day   DATE NOT NULL,
  instrument_id  BIGINT NOT NULL REFERENCES instrument(instrument_id),
  side           TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  qty            NUMERIC NOT NULL CHECK (qty > 0),
  ref_price      NUMERIC NOT NULL CHECK (ref_price > 0),   -- the decision day's close the size was worked out from
  reason         TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'FILLED', 'FAILED')),
  created_at     TIMESTAMPTZ NOT NULL,
  expires_at     TIMESTAMPTZ NOT NULL,
  decided_at     TIMESTAMPTZ,
  decided_by     UUID REFERENCES portal_user(user_id),
  fill_day       DATE,
  fill_price     NUMERIC,
  fill_commission NUMERIC,
  fill_charges   JSONB,
  filled_at      TIMESTAMPTZ,
  failure        TEXT
);
CREATE INDEX paper_order_user ON paper_order (user_id, status, created_at DESC);

CREATE TABLE paper_equity (
  user_id UUID NOT NULL REFERENCES paper_account(user_id),
  day     DATE NOT NULL,
  equity  NUMERIC NOT NULL,
  cash    NUMERIC NOT NULL,
  PRIMARY KEY (user_id, day)
);

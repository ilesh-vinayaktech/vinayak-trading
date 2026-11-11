-- Paper trading, one account per portal user. UNVALIDATED research: the strategy behind these accounts has not passed the
-- project's validation gates, so nothing here may be promoted to live trading.
-- paper_account holds the settings; paper_event is the account's append-only book (fills, splits, dividends, flagged
-- actions). Cash, positions, P&L and reconciliation are never stored: they are rebuilt by replaying the events through
-- the same Ledger the backtest engine uses, so a paper account and a backtest cannot disagree about the arithmetic.
CREATE TABLE paper_account (
  user_id         UUID PRIMARY KEY REFERENCES portal_user(user_id),
  strategy_id     TEXT NOT NULL,
  params          JSONB NOT NULL,
  enabled         BOOLEAN NOT NULL DEFAULT true,
  mode            TEXT NOT NULL DEFAULT 'PAPER' CHECK (mode = 'PAPER'),  -- real trading is not available
  initial_cash    NUMERIC NOT NULL CHECK (initial_cash > 0),
  started_on      DATE NOT NULL,
  actions_through DATE NOT NULL,      -- corporate actions are applied up to and including this date
  attention       TEXT,               -- not null: an action the books cannot value; the account is paused
  created_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE paper_event (
  event_id      BIGSERIAL PRIMARY KEY,
  user_id       UUID NOT NULL REFERENCES paper_account(user_id),
  day           DATE NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('BUY', 'SELL', 'SPLIT', 'DIVIDEND', 'UNMODELLED')),
  instrument_id BIGINT NOT NULL REFERENCES instrument(instrument_id),
  qty           NUMERIC,
  price         NUMERIC,
  commission    NUMERIC,
  charges       JSONB,                -- [[type, amount], ...] besides the commission
  num           NUMERIC,
  den           NUMERIC,
  amount        NUMERIC,              -- dividend per share
  note          TEXT,                 -- UNMODELLED: the action kind
  ref           TEXT NOT NULL,        -- idempotency key: posting the same ref twice changes nothing
  created_at    TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, ref)
);
CREATE INDEX paper_event_user ON paper_event (user_id, event_id);

CREATE FUNCTION paper_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'paper_event is append-only';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER paper_event_no_change BEFORE UPDATE OR DELETE ON paper_event
  FOR EACH ROW EXECUTE FUNCTION paper_event_immutable();
CREATE TRIGGER paper_event_no_wipe BEFORE TRUNCATE ON paper_event
  FOR EACH STATEMENT EXECUTE FUNCTION paper_event_immutable();

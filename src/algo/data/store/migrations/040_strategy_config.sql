-- Saved, named strategy settings, per user. A paper account picks one: the config's settings are copied onto the account
-- (paper_account.universe/max_instruments/timeframe/params stay what the runner reads), and saving a config updates every
-- account that uses it. Existing accounts get a config made from their current settings.
CREATE TABLE strategy_config (
  config_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id   UUID NOT NULL REFERENCES portal_user(user_id),
  name            TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  strategy_id     TEXT NOT NULL,
  universe        TEXT NOT NULL CHECK (universe IN ('nifty50', 'nifty100', 'nifty200', 'midcap100', 'nifty500')),
  max_instruments INT CHECK (max_instruments BETWEEN 5 AND 500),
  timeframe       TEXT NOT NULL CHECK (timeframe IN ('1D')),
  params          JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL,
  UNIQUE (owner_user_id, name)
);

ALTER TABLE paper_account ADD COLUMN config_id UUID REFERENCES strategy_config(config_id);

WITH made AS (
  INSERT INTO strategy_config (owner_user_id, name, strategy_id, universe, max_instruments, timeframe, params, created_at)
  SELECT user_id, 'My paper strategy', strategy_id, universe, max_instruments, timeframe, params, created_at FROM paper_account
  RETURNING config_id, owner_user_id
)
UPDATE paper_account a SET config_id = made.config_id FROM made WHERE a.user_id = made.owner_user_id;

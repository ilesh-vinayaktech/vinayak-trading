-- A paper account can follow a screener strategy: the account carries a copy of the strategy's rules (screen), like it carries
-- a copy of the other settings, and universe is then 'segments' (the market-cap classes named inside screen).
ALTER TABLE paper_account ADD COLUMN screen JSONB;
ALTER TABLE paper_account DROP CONSTRAINT paper_account_universe_check;
ALTER TABLE paper_account ADD CONSTRAINT paper_account_universe_check
  CHECK (universe IN ('nifty50', 'nifty100', 'nifty200', 'midcap100', 'nifty500', 'segments'));
ALTER TABLE paper_account ADD CONSTRAINT paper_account_screen_check
  CHECK ((strategy_id = 'screener') = (screen IS NOT NULL));

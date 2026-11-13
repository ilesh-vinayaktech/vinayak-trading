-- A screener saved as a strategy. strategy_config.screen holds {"screen": the rules, "segments": the market-cap classes it
-- picks from}; universe is then 'segments' (the nifty-list universes belong to the trend-pullback strategy and the paper
-- runner). params keeps max_positions.
ALTER TABLE strategy_config ADD COLUMN screen JSONB;
ALTER TABLE strategy_config DROP CONSTRAINT strategy_config_universe_check;
ALTER TABLE strategy_config ADD CONSTRAINT strategy_config_universe_check
  CHECK (universe IN ('nifty50', 'nifty100', 'nifty200', 'midcap100', 'nifty500', 'segments'));
ALTER TABLE strategy_config ADD CONSTRAINT strategy_config_screen_check
  CHECK ((strategy_id = 'screener') = (screen IS NOT NULL));

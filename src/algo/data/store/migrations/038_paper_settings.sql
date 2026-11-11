-- What a paper account's strategy runs on, chosen per user.
--   universe:        which index the strategy may trade (see algo.paper.universe.UNIVERSES)
--   max_instruments: keep only the N most liquid of that universe (20-day average traded value); NULL = all of it
--   timeframe:       the bar size the strategy decides on. Only the daily bar is supported today; intraday timeframes
--                    need intraday history in the strategy's Context and an intraday schedule, which do not exist yet.
ALTER TABLE paper_account
  ADD COLUMN universe        TEXT NOT NULL DEFAULT 'nifty200' CHECK (universe IN ('nifty50', 'nifty100', 'nifty200', 'midcap100', 'nifty500')),
  ADD COLUMN max_instruments INT CHECK (max_instruments BETWEEN 5 AND 500),
  ADD COLUMN timeframe       TEXT NOT NULL DEFAULT '1D' CHECK (timeframe IN ('1D'));

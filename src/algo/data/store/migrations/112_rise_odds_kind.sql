-- Rise odds get a second kind. 'rel' (the first, migration 111): does the stock beat the median stock over the next 5 sessions. 'up': does it close higher than today 5 sessions on, from the
-- stock's own history only (no market state: market-state features made it a market-timing model that was worse than chance on later years; scripts/study_own_direction.py).
ALTER TABLE rise_odds_model ADD COLUMN kind TEXT NOT NULL DEFAULT 'rel' CHECK (kind IN ('rel', 'up'));
ALTER TABLE rise_odds ADD COLUMN kind TEXT NOT NULL DEFAULT 'rel' CHECK (kind IN ('rel', 'up'));
ALTER TABLE rise_odds DROP CONSTRAINT rise_odds_pkey;
ALTER TABLE rise_odds ADD PRIMARY KEY (day, instrument_id, horizon, kind);
DROP INDEX rise_odds_instrument;
CREATE INDEX rise_odds_instrument ON rise_odds (instrument_id, kind, day);

-- The daily Kite instrument dump (every exchange) and what it changed in our token mapping.
-- kite_instrument keeps every token we have ever mapped (history loads and old orders refer to them); `active` says
-- whether the token is part of today's mapping, and is what the live feed subscribes to.
ALTER TABLE kite_instrument ADD COLUMN active BOOLEAN NOT NULL DEFAULT true;

CREATE TABLE kite_instrument_refresh (
  refresh_day   DATE PRIMARY KEY,           -- IST date of the refresh; a repeat on the same day replaces the row
  fetched_at    TIMESTAMPTZ NOT NULL,
  raw_sha256    TEXT NOT NULL,              -- of the dump exactly as received (archived in the lake)
  total_rows    INT NOT NULL,               -- every instrument on every exchange
  nse_equities  INT NOT NULL,
  mapped        INT NOT NULL,               -- of the index list, how many got a token
  unmatched     JSONB NOT NULL,             -- [[symbol, reason], ...]
  added         JSONB NOT NULL,             -- symbols newly mapped
  dropped       JSONB NOT NULL,             -- symbols that were mapped and no longer are
  token_changes JSONB NOT NULL              -- [[symbol, old token, new token], ...]
);

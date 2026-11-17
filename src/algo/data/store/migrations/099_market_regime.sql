-- The market zone, one row per trading day (TODO 6.3): breadth counted from every liquid stock's daily bar, and the fear/greed score, label and
-- trend/volatility regime computed from it and from the index series (algo/market). Rebuilt from the bars, so a row can be recomputed at any time.
CREATE TABLE market_regime_daily (
  day          DATE PRIMARY KEY,           -- IST trading day
  universe     INT NOT NULL,               -- liquid stocks that traded (20-day average traded value of at least 1 crore)
  advancers    INT NOT NULL,
  decliners    INT NOT NULL,
  unchanged    INT NOT NULL,
  n50          INT NOT NULL,               -- stocks with 50 days of history (the base of above50)
  above50      INT NOT NULL,
  n200         INT NOT NULL,
  above200     INT NOT NULL,
  highs        INT NOT NULL,               -- closes at a new 52-week high
  lows         INT NOT NULL,
  fear_greed   NUMERIC,                    -- 0 (extreme fear) to 100 (extreme greed); null until enough history
  label        TEXT,
  trend        TEXT,                       -- BULL | BEAR | SIDEWAYS | UNKNOWN
  volatility   TEXT,                       -- CALM | NORMAL | STRESSED | UNKNOWN
  components   JSONB,                       -- each signal's 0 to 100 score
  computed_at  TIMESTAMPTZ NOT NULL
);

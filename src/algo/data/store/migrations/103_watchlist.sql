-- A person's watchlist (TODO 6.8): the stocks they want to keep an eye on. Personal and read by nothing else (no strategy, no order).
CREATE TABLE watchlist (
  user_id       UUID   NOT NULL,
  instrument_id BIGINT NOT NULL,
  added_at      TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_id, instrument_id)
);

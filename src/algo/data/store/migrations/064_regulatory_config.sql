-- What the exchange and the broker require of an algo order (order-rate limit, order types and market protection, order tagging, static IP),
-- each with the circular it comes from and the day a person last checked it is still true. Append-only: a re-check or a change is a new
-- row (the newest per exchange, segment and topic is the one in force). Live trading is refused when a required topic has no row or its
-- last check is too old (algo.execution.regulatory).
CREATE TABLE regulatory_config (
  id            BIGSERIAL PRIMARY KEY,
  exchange      TEXT NOT NULL,
  segment       TEXT NOT NULL,
  topic         TEXT NOT NULL,
  value         JSONB NOT NULL,
  effective_from DATE NOT NULL,
  source        TEXT NOT NULL CHECK (source <> ''),   -- the circular or page it was read from
  last_verified DATE NOT NULL,
  verified_by   TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX regulatory_config_topic ON regulatory_config (exchange, segment, topic, id DESC);
CREATE FUNCTION regulatory_config_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'regulatory_config is append-only: add a new row';
END
$$ LANGUAGE plpgsql;
CREATE TRIGGER regulatory_config_no_change BEFORE UPDATE OR DELETE ON regulatory_config
  FOR EACH ROW EXECUTE FUNCTION regulatory_config_immutable();

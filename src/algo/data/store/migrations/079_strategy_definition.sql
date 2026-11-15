-- Strategy definitions (plan.md sections 7.2 and 7.3): every version is an immutable row. A change is a NEW version that points at the one before it
-- and says why; nothing is ever updated or removed, so a result that names (strategy_id, version, sha256) can always be reproduced from what is stored.
-- There is deliberately no status column: a definition is only a description. Becoming usable for paper or live goes through the existing validation
-- and lifecycle gates, which this table cannot bypass because it carries no promotion state at all.
CREATE TABLE strategy_definition (
  definition_id     BIGSERIAL PRIMARY KEY,
  strategy_id       TEXT NOT NULL,
  version           INTEGER NOT NULL CHECK (version >= 1),
  parent_version    INTEGER,
  reason            TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
  definition        JSONB NOT NULL,
  definition_sha256 TEXT NOT NULL CHECK (length(definition_sha256) = 64),
  created_by        TEXT NOT NULL CHECK (length(btrim(created_by)) > 0),
  created_at        TIMESTAMPTZ NOT NULL,
  UNIQUE (strategy_id, version),
  CHECK ((version = 1 AND parent_version IS NULL) OR (version > 1 AND parent_version = version - 1))
);
CREATE INDEX strategy_definition_sha ON strategy_definition (definition_sha256);
CREATE FUNCTION strategy_definition_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'strategy_definition is insert-only: a version is never changed or removed; make a new version';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER strategy_definition_insert_only BEFORE UPDATE OR DELETE ON strategy_definition FOR EACH ROW EXECUTE FUNCTION strategy_definition_insert_only();

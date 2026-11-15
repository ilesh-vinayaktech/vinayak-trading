-- Research memory (plan.md phase 4): what was tried, what failed and why, what was decided. Insert-only; a correction is a new note.
-- A note derived from a record elsewhere (an alpha hypothesis) carries that record's kind and id, and there is at most one note per record.
CREATE TABLE research_note (
  note_id     BIGSERIAL PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('FINDING', 'FAILURE', 'DECISION', 'LESSON')),
  subject     TEXT NOT NULL CHECK (length(btrim(subject)) > 0),
  body        TEXT NOT NULL CHECK (length(btrim(body)) > 0),
  tags        TEXT[] NOT NULL DEFAULT '{}',
  source_kind TEXT,
  source_id   BIGINT,
  created_by  TEXT NOT NULL CHECK (length(btrim(created_by)) > 0),
  created_at  TIMESTAMPTZ NOT NULL,
  CHECK ((source_kind IS NULL) = (source_id IS NULL))
);
CREATE UNIQUE INDEX research_note_source ON research_note (source_kind, source_id) WHERE source_kind IS NOT NULL;
CREATE INDEX research_note_subject ON research_note (subject);
CREATE INDEX research_note_tags ON research_note USING GIN (tags);
CREATE FUNCTION research_note_insert_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'research_note is insert-only: a note is never changed or removed; write a new one';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER research_note_insert_only BEFORE UPDATE OR DELETE ON research_note FOR EACH ROW EXECUTE FUNCTION research_note_insert_only();

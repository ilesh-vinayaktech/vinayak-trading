-- A later release can void or re-date what an earlier one announced (e.g. the March 2020
-- rebalancing). The evidence rows are never edited; an override says, with its authority and quote,
-- that the matching rows never took effect as announced.
CREATE TABLE index_release_override (
  override_id     BIGSERIAL PRIMARY KEY,
  doc_id          TEXT NOT NULL,             -- the superseded release
  effective_from  DATE NOT NULL,             -- only rows announced for this date
  effect          TEXT NOT NULL CHECK (effect IN ('VOID')),
  authority_doc   TEXT NOT NULL,             -- the release that supersedes it
  authority_quote TEXT NOT NULL CHECK (length(btrim(authority_quote)) > 0),
  recorded_at     TIMESTAMPTZ NOT NULL,
  UNIQUE (doc_id, effective_from, effect)
);

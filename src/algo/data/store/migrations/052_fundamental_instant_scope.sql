-- Balance-sheet figures are reported at a date, not over a period: a third scope next to QUARTER and YTD.
-- Facts named like the XBRL element (CamelCase) are the full filing; the lower-case metrics are the curated P&L set.
ALTER TABLE fundamental_fact DROP CONSTRAINT fundamental_fact_scope_check;
ALTER TABLE fundamental_fact ADD CONSTRAINT fundamental_fact_scope_check CHECK (scope IN ('QUARTER','YTD','INSTANT'));

-- A spun-off entity can be included in the indices BEFORE its symbol is alias-valid (JIOFIN was in the
-- Nifty 50/100/200 from 2023-07-20 but listed, and the alias starts, 2023-08-21). The pre-listing
-- entity then carries the listing's own symbol, so the placeholder is that symbol, not a DUMMY one.
ALTER TABLE index_placeholder_replacement DROP CONSTRAINT index_placeholder_replacement_placeholder_check;
ALTER TABLE index_placeholder_replacement
  ADD CONSTRAINT index_placeholder_replacement_placeholder_check
  CHECK (placeholder LIKE 'DUMMY%' OR placeholder = symbol);

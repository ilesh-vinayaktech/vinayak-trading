-- Evidence-backed lifecycle for corporate-action resolutions.
--   provisional            estimated / unverified factor: research use only, never strict
--   verified               factor backed by an authoritative source (filing / exchange notice)
--   no_adjustment_verified reviewed against a source: no price adjustment needed
--   ignored_with_reason    explicitly excluded, documented reason only
--   rejected               the detected event was wrong
-- confirmed_by / confirmed_at record WHO verified and WHEN.
ALTER TABLE action_resolution
  ADD COLUMN status TEXT NOT NULL DEFAULT 'provisional'
    CHECK (status IN ('provisional','verified','no_adjustment_verified','ignored_with_reason','rejected')),
  ADD COLUMN source_type TEXT,    -- e.g. company_filing | exchange_notice | nse_feed_subject
  ADD COLUMN source_url TEXT,
  ADD COLUMN source_hash TEXT;    -- sha256 of the stored source document, when kept

UPDATE action_resolution SET status = CASE
  WHEN treatment = 'ignore' THEN 'ignored_with_reason'
  ELSE 'provisional' END;        -- nothing was evidence-backed before this migration

ALTER TABLE action_resolution ADD CONSTRAINT resolution_status_consistent CHECK (
     (status = 'provisional' AND treatment = 'factor')
  OR (status = 'verified' AND treatment = 'factor'
      AND source_type IS NOT NULL AND source_url IS NOT NULL AND confirmed_by IS NOT NULL)
  OR (status = 'no_adjustment_verified' AND treatment = 'ignore'
      AND source_type IS NOT NULL AND source_url IS NOT NULL AND confirmed_by IS NOT NULL)
  OR (status IN ('ignored_with_reason','rejected') AND treatment = 'ignore'));

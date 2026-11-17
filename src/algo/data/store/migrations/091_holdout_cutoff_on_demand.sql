-- Holdout policy v3, owner amendment 2026-11-17: after Batch 1 a strategy can be submitted at any time (no fixed calendar dates). A cutoff is recorded when the owner submits
-- candidates ('ON_DEMAND'); the snapshot still records who was in it, immutably. The slot budget, seeds, marker and the stricter bar are unchanged.
ALTER TABLE holdout_cutoff DROP COLUMN due_on;   -- takes its check and the quarter index with it
ALTER TABLE holdout_cutoff DROP CONSTRAINT holdout_cutoff_kind_check;
ALTER TABLE holdout_cutoff ADD CONSTRAINT holdout_cutoff_kind_check CHECK (kind IN ('BATCH1', 'ON_DEMAND'));

-- One row per instrument and bar timestamp: the preferred source wins (Kite, the primary copy, then NSE bhavcopy, the backup copy -- the order
-- documented in algo.data.price_source), and within a source the newest dataset_version (a provider's correction supersedes the earlier row).
-- A day the preferred source lacks falls back to the next source; nothing is filled or interpolated.
CREATE VIEW bar_canonical AS
SELECT DISTINCT ON (instrument_id, ts) *
FROM bar_1d
ORDER BY instrument_id, ts,
         CASE source WHEN 'kite' THEN 0 WHEN 'nse' THEN 1 ELSE 2 END,
         dataset_version DESC;

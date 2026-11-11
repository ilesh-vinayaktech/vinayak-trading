-- The raw response of each Kite request is archived in the lake (raw/kite/minute_<token>/dt=<window start>, gzip);
-- this is the sha256 of the stored file, so a window can be traced to the exact bytes Kite sent. NULL = loaded before archiving.
ALTER TABLE kite_fetch ADD COLUMN raw_sha256 TEXT;

-- One row per long-running process, replaced every few seconds by that process. The heartbeat check (scripts/check_heartbeats.py, job
-- `heartbeat-check`) alerts when an expected process is missing, silent, degraded or stopped. The live feed keeps its own row in
-- feed_status and is read from there.
CREATE TABLE process_heartbeat (
  process    TEXT PRIMARY KEY CHECK (process <> ''),
  pid        INT NOT NULL,
  host       TEXT NOT NULL,
  state      TEXT NOT NULL CHECK (state IN ('STARTING', 'RUNNING', 'DEGRADED', 'STOPPED')),
  detail     TEXT NOT NULL DEFAULT '',
  started_at TIMESTAMPTZ NOT NULL,
  beat_at    TIMESTAMPTZ NOT NULL
);

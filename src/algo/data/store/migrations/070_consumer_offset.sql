-- A durable cursor for whatever reads the live bars (docs: TODO 5.3). A consumer is identified by a name; its offset is the last bar it
-- handled, ordered by when the feed WROTE it (built_at, then instrument, then minute), so a bar that arrives late for an earlier minute
-- is still delivered. The index makes "the bars after this cursor" a short range scan on a table that grows by ~600,000 rows a day.
CREATE INDEX live_bar_1m_built ON live_bar_1m (built_at, instrument_id, ts);
CREATE TABLE consumer_offset (
  consumer      TEXT PRIMARY KEY CHECK (consumer <> ''),
  built_at      TIMESTAMPTZ NOT NULL,
  instrument_id BIGINT NOT NULL,
  ts            TIMESTAMPTZ NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL
);

-- Market news headlines from public RSS feeds with a crude sentiment reading (TODO 6.7, algo/data/news.py). Headline, the feed's own summary and the link only.
-- published_at is when the publisher says it came out; first_seen_at is when we first fetched it: nothing may be used as known before the later of the two.
CREATE TABLE news_item (
  item_id       TEXT PRIMARY KEY,            -- sha1 of the link
  source        TEXT NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT NOT NULL DEFAULT '',
  url           TEXT NOT NULL,
  published_at  TIMESTAMPTZ NOT NULL,        -- UTC
  first_seen_at TIMESTAMPTZ NOT NULL,        -- UTC
  sentiment     REAL CHECK (sentiment BETWEEN -1 AND 1),   -- NULL: no word of the list appeared (unknown, not neutral)
  hits          INT NOT NULL DEFAULT 0,
  symbols       TEXT[] NOT NULL DEFAULT '{}' -- listed stocks named in the text
);
CREATE INDEX news_item_published ON news_item (published_at DESC);
CREATE INDEX news_item_symbols ON news_item USING gin (symbols);

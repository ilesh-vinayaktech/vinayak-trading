-- A second reading of each headline from the Laya model (a local ONNX decision model, tools/laya), kept beside the keyword reading so the two can be compared.
-- laya_sentiment is -1 (very negative for the share price) to +1 (very positive); laya_confidence is the model's own probability for its answer (0 to 1).
ALTER TABLE news_item
  ADD COLUMN laya_sentiment  REAL,
  ADD COLUMN laya_confidence REAL,
  ADD COLUMN laya_scored_at  TIMESTAMPTZ;
CREATE INDEX news_item_unscored ON news_item (published_at) WHERE laya_sentiment IS NULL;

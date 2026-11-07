-- Every release gets an explicit classification and reason; text is kept for anything a person must
-- read. "The parser ran" is not a classification.
ALTER TABLE index_release_document
  ADD COLUMN classification TEXT NOT NULL DEFAULT 'PARSED' CHECK (classification IN
    ('PARSED', 'MANUAL_REVIEW_REQUIRED', 'NOT_RELEVANT', 'UNSUPPORTED_FORMAT', 'SOURCE_UNAVAILABLE')),
  ADD COLUMN classification_reason TEXT NOT NULL DEFAULT '',
  ADD COLUMN extracted_text TEXT;

-- The owner chooses how an order is sent when approving it: MARKET (fills at the next live minute's open, with slippage) or
-- LIMIT (fills only at the limit price or better; unfilled when the session ends = not filled before the order expired).
ALTER TABLE paper_order
  ADD COLUMN order_type TEXT NOT NULL DEFAULT 'MARKET' CHECK (order_type IN ('MARKET', 'LIMIT')),
  ADD COLUMN limit_price NUMERIC CHECK (limit_price > 0),
  ADD CONSTRAINT paper_order_limit_price CHECK ((order_type = 'LIMIT') = (limit_price IS NOT NULL));

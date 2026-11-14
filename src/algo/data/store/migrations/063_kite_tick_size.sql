-- The exchange's price step per stock, from Kite's instrument dump (`tick_size`: 0.05 for most shares, 0.01 for some funds and
-- low-priced shares). A limit price must be a multiple of it. NULL until the next daily instrument refresh stores it.
ALTER TABLE kite_instrument ADD COLUMN tick_size NUMERIC CHECK (tick_size > 0);

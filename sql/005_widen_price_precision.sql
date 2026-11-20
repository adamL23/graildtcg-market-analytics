-- Preserve TCGAPI.dev history values such as 0.1324 without rounding.
-- NUMERIC(14,4) retains the prior ten-digit integer capacity while adding scale.

BEGIN;

ALTER TABLE price_history
    ALTER COLUMN market_price TYPE NUMERIC(14, 4),
    ALTER COLUMN low_price TYPE NUMERIC(14, 4),
    ALTER COLUMN avg_sales_price TYPE NUMERIC(14, 4);

COMMIT;

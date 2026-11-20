-- Applied only to the already-migrated local Task 10 database.
-- Fresh databases receive these final names directly from 010_create_reporting_views.sql.

BEGIN;

ALTER VIEW reporting.cards RENAME TO dim_cards;
ALTER VIEW reporting.price_history RENAME TO fact_price_history;
ALTER VIEW reporting.current_prices RENAME TO fact_current_prices;
ALTER VIEW reporting.condition_prices RENAME TO fact_condition_prices;
ALTER VIEW reporting.graded_price_summaries
    RENAME TO fact_graded_price_summaries;
ALTER VIEW reporting.reported_sale_observations
    RENAME TO fact_reported_sale_observations;

COMMIT;

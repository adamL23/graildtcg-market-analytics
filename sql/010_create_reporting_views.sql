-- Task 10: lightweight Power BI reporting surface over preserved operational data.

BEGIN;

CREATE SCHEMA reporting;

REVOKE ALL ON SCHEMA reporting FROM PUBLIC;

CREATE VIEW reporting.dim_cards AS
SELECT
    c.card_id,
    c.tcgapi_card_id,
    c.tcgplayer_id,
    c.card_name,
    c.card_number,
    c.rarity,
    c.variant_name,
    c.image_url,
    c.set_id,
    s.tcgapi_set_id,
    s.source_set_key,
    s.game_id,
    s.game_name,
    s.set_name,
    s.set_code,
    s.language_code,
    s.region_code,
    s.release_date,
    c.source_name AS card_source_name,
    c.source_observed_at AS card_source_observed_at,
    c.loaded_at AS card_loaded_at,
    s.source_name AS set_source_name,
    s.source_observed_at AS set_source_observed_at,
    s.loaded_at AS set_loaded_at
FROM public.cards AS c
JOIN public.sets AS s ON s.set_id = c.set_id;

COMMENT ON VIEW reporting.dim_cards IS
    'Power BI card dimension. Grain: exactly one row per public.cards.card_id (canonical TCGAPI card identity).';

CREATE VIEW reporting.fact_price_history AS
SELECT
    price_history_id,
    card_id,
    observation_date,
    printing,
    market_price,
    low_price,
    avg_sales_price,
    sales_volume,
    source_name,
    currency_code,
    source_file,
    source_row_number,
    source_record_hash,
    loaded_at
FROM public.price_history;

COMMENT ON VIEW reporting.fact_price_history IS
    'Historical price fact. Grain: one canonical daily observation per card, source, printing, currency, and observation_date; no aggregation is applied.';

CREATE VIEW reporting.fact_current_prices AS
SELECT
    current_price_id,
    card_id,
    printing,
    market_price,
    low_price,
    median_price,
    lowest_with_shipping,
    total_listings,
    market_price_as_of,
    provider_observed_at,
    no_market_price_since,
    market_price_is_zero,
    source_name,
    currency_code,
    source_file,
    source_row_number,
    source_record_hash,
    loaded_at
FROM public.current_prices;

COMMENT ON VIEW reporting.fact_current_prices IS
    'Current price fact. Grain: one latest provider snapshot per card, source, currency, and printing; no aggregation is applied.';

CREATE VIEW reporting.fact_condition_prices AS
SELECT
    condition_price_id,
    card_id,
    printing,
    condition_name,
    listing_language,
    low_price,
    lowest_with_shipping,
    median_with_shipping,
    sample_count,
    provider_observed_at,
    source_name,
    currency_code,
    source_file,
    source_row_number,
    source_record_hash,
    loaded_at
FROM public.condition_prices;

COMMENT ON VIEW reporting.fact_condition_prices IS
    'Condition price fact. Grain: one latest provider snapshot per card, source, currency, printing, condition, and listing language; no aggregation is applied.';

CREATE VIEW reporting.fact_graded_price_summaries AS
SELECT
    graded_price_summary_id,
    card_id,
    printing,
    grade_label,
    median_30d,
    sales_30d,
    last_sale_price,
    last_sold_date,
    ungraded_days,
    graded_days,
    provider_as_of,
    is_reported_in_latest_snapshot,
    CASE
        WHEN is_reported_in_latest_snapshot THEN 'Current provider snapshot'
        ELSE 'Last-known observation'
    END AS reporting_status,
    coverage_checked_at,
    source_name,
    currency_code,
    source_file,
    source_row_number,
    source_record_hash,
    loaded_at
FROM public.graded_price_summaries;

COMMENT ON VIEW reporting.fact_graded_price_summaries IS
    'Graded summary fact. Grain: one canonical summary per card, source, currency, printing, and raw grade label; current and retained last-known rows remain distinguishable.';

CREATE VIEW reporting.fact_reported_sale_observations AS
SELECT
    reported_sale_observation_id,
    source_snapshot_key,
    card_id,
    printing,
    source_row_number,
    sold_date,
    price,
    best_offer,
    list_price,
    grade_label,
    condition_label,
    listing_title,
    listing_url,
    currency_code,
    provider_as_of,
    source_captured_at,
    source_name,
    source_file,
    source_record_hash,
    loaded_at,
    'Provider-reported, unverified observation'::TEXT
        AS verification_status
FROM public.reported_sale_observations
WHERE source_snapshot_key =
    'tcgapi.dev:ebay_sales:20261118T035224841879Z';

COMMENT ON VIEW reporting.fact_reported_sale_observations IS
    'Reported sale observation fact pinned to completed snapshot tcgapi.dev:ebay_sales:20261118T035224841879Z. Grain: one source-array observation per snapshot, card, printing, and source_row_number; not a verified unique transaction.';

REVOKE ALL ON ALL TABLES IN SCHEMA reporting FROM PUBLIC;

COMMIT;

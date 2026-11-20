-- Task 10 read-only verification of view grains, counts, and data semantics.

SELECT view_name, row_count
FROM (
    SELECT 'dim_cards'::TEXT, count(*) FROM reporting.dim_cards
    UNION ALL SELECT 'fact_price_history', count(*) FROM reporting.fact_price_history
    UNION ALL SELECT 'fact_current_prices', count(*) FROM reporting.fact_current_prices
    UNION ALL SELECT 'fact_condition_prices', count(*) FROM reporting.fact_condition_prices
    UNION ALL SELECT 'fact_graded_price_summaries', count(*) FROM reporting.fact_graded_price_summaries
    UNION ALL SELECT 'fact_reported_sale_observations', count(*) FROM reporting.fact_reported_sale_observations
) AS counts(view_name, row_count)
ORDER BY view_name;

SELECT
    (SELECT count(*) FROM reporting.dim_cards) =
        (SELECT count(*) FROM public.cards) AS cards_grain_preserved,
    (SELECT count(*) FROM reporting.fact_price_history) =
        (SELECT count(*) FROM public.price_history) AS history_grain_preserved,
    (SELECT count(*) FROM reporting.fact_current_prices) =
        (SELECT count(*) FROM public.current_prices) AS current_grain_preserved,
    (SELECT count(*) FROM reporting.fact_condition_prices) =
        (SELECT count(*) FROM public.condition_prices) AS condition_grain_preserved,
    (SELECT count(*) FROM reporting.fact_graded_price_summaries) =
        (SELECT count(*) FROM public.graded_price_summaries) AS graded_grain_preserved,
    (SELECT count(*) FROM reporting.fact_reported_sale_observations) =
        (SELECT count(*) FROM public.reported_sale_observations
         WHERE source_snapshot_key =
             'tcgapi.dev:ebay_sales:20261118T035224841879Z')
        AS reported_sales_pinned_grain_preserved;

SELECT
    count(*) AS reported_sale_rows,
    count(DISTINCT source_snapshot_key) AS snapshot_key_count,
    min(source_snapshot_key) AS pinned_snapshot_key,
    count(*) FILTER (WHERE currency_code IS NULL) AS null_currency_rows,
    count(*) FILTER (WHERE currency_code IS NOT NULL) AS populated_currency_rows,
    count(*) FILTER (
        WHERE verification_status <> 'Provider-reported, unverified observation'
    ) AS invalid_verification_labels
FROM reporting.fact_reported_sale_observations;

SELECT
    count(*) AS graded_rows,
    count(*) FILTER (WHERE is_reported_in_latest_snapshot) AS current_rows,
    count(*) FILTER (WHERE NOT is_reported_in_latest_snapshot) AS last_known_rows,
    count(*) FILTER (
        WHERE is_reported_in_latest_snapshot
          AND reporting_status <> 'Current provider snapshot'
    ) AS invalid_current_labels,
    count(*) FILTER (
        WHERE NOT is_reported_in_latest_snapshot
          AND reporting_status <> 'Last-known observation'
    ) AS invalid_last_known_labels
FROM reporting.fact_graded_price_summaries;

SELECT fact_name, orphan_rows
FROM (
    SELECT 'price_history'::TEXT, count(*)
    FROM reporting.fact_price_history AS f
    LEFT JOIN reporting.dim_cards AS d ON d.card_id = f.card_id
    WHERE d.card_id IS NULL
    UNION ALL
    SELECT 'current_prices', count(*)
    FROM reporting.fact_current_prices AS f
    LEFT JOIN reporting.dim_cards AS d ON d.card_id = f.card_id
    WHERE d.card_id IS NULL
    UNION ALL
    SELECT 'condition_prices', count(*)
    FROM reporting.fact_condition_prices AS f
    LEFT JOIN reporting.dim_cards AS d ON d.card_id = f.card_id
    WHERE d.card_id IS NULL
    UNION ALL
    SELECT 'graded_price_summaries', count(*)
    FROM reporting.fact_graded_price_summaries AS f
    LEFT JOIN reporting.dim_cards AS d ON d.card_id = f.card_id
    WHERE d.card_id IS NULL
    UNION ALL
    SELECT 'reported_sale_observations', count(*)
    FROM reporting.fact_reported_sale_observations AS f
    LEFT JOIN reporting.dim_cards AS d ON d.card_id = f.card_id
    WHERE d.card_id IS NULL
) AS orphans(fact_name, orphan_rows)
ORDER BY fact_name;

SELECT
    (SELECT count(*) FROM public.cards) AS operational_cards,
    (SELECT count(*) FROM public.price_history) AS operational_history,
    (SELECT count(*) FROM public.current_prices) AS operational_current,
    (SELECT count(*) FROM public.condition_prices) AS operational_conditions,
    (SELECT count(*) FROM public.graded_price_summaries) AS operational_graded,
    (SELECT count(*) FROM public.reported_sale_observations) AS operational_sales;

-- Task 8 read-only verification for aggregated graded sold-price summaries.

SELECT
    s.set_name,
    s.language_code,
    count(DISTINCT c.card_id) AS catalog_cards,
    count(DISTINCT gps.card_id) FILTER (
        WHERE gps.is_reported_in_latest_snapshot
    ) AS cards_with_current_graded_summaries,
    count(gps.graded_price_summary_id) FILTER (
        WHERE gps.is_reported_in_latest_snapshot
    ) AS currently_reported_grade_rows,
    count(gps.graded_price_summary_id) FILTER (
        WHERE NOT gps.is_reported_in_latest_snapshot
    ) AS retained_last_known_grade_rows,
    max(gps.provider_as_of) AS latest_provider_as_of
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN graded_price_summaries AS gps ON gps.card_id = c.card_id
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT count(*) AS orphan_graded_summary_rows
FROM graded_price_summaries AS gps
LEFT JOIN cards AS c ON c.card_id = gps.card_id
WHERE c.card_id IS NULL;

SELECT count(*) AS duplicate_canonical_groups
FROM (
    SELECT card_id, source_name, currency_code, printing, grade_label
    FROM graded_price_summaries
    GROUP BY card_id, source_name, currency_code, printing, grade_label
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS graded_summary_rows,
    count(*) FILTER (WHERE is_reported_in_latest_snapshot) AS currently_reported,
    count(*) FILTER (WHERE NOT is_reported_in_latest_snapshot) AS last_known,
    count(*) FILTER (WHERE median_30d IS NULL) AS median_nulls,
    count(*) FILTER (WHERE median_30d = 0) AS median_zeroes,
    count(*) FILTER (
        WHERE median_30d IS NULL
          AND last_sale_price IS NOT NULL
          AND last_sold_date IS NOT NULL
    ) AS null_median_with_historical_last_sale,
    count(*) FILTER (WHERE sales_30d = 0) AS zero_sales_windows,
    count(*) FILTER (WHERE graded_days = 30) AS complete_graded_windows,
    count(*) FILTER (
        WHERE graded_days IS NULL OR graded_days < 30
    ) AS partial_or_unknown_graded_windows
FROM graded_price_summaries;

SELECT
    graded_days,
    ungraded_days,
    count(*) AS graded_summary_rows
FROM graded_price_summaries
GROUP BY graded_days, ungraded_days
ORDER BY graded_days NULLS FIRST, ungraded_days NULLS FIRST;

SELECT count(*) AS invalid_numeric_date_or_window_rows
FROM graded_price_summaries
WHERE median_30d < 0
   OR sales_30d < 0
   OR last_sale_price < 0
   OR ungraded_days NOT BETWEEN 0 AND 30
   OR graded_days NOT BETWEEN 0 AND 30
   OR last_sold_date > provider_as_of;

SELECT
    grade_label,
    count(*) AS graded_summary_rows,
    count(*) FILTER (WHERE median_30d IS NOT NULL) AS rows_with_30d_median,
    sum(sales_30d) AS reported_sales_30d
FROM graded_price_summaries
WHERE is_reported_in_latest_snapshot
GROUP BY grade_label
ORDER BY graded_summary_rows DESC, grade_label;

SELECT
    (SELECT count(*) FROM cards) AS catalog_cards,
    (SELECT count(*) FROM current_prices) AS current_price_rows_unchanged,
    (SELECT count(*) FROM condition_prices) AS condition_price_rows_unchanged,
    (SELECT count(*) FROM price_history) AS historical_rows_unchanged;

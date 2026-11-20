-- Task 7 read-only verification for latest cached condition-price snapshots.

SELECT
    s.set_name,
    s.language_code,
    count(DISTINCT c.card_id) AS catalog_cards,
    count(DISTINCT cp.card_id) AS cards_with_condition_prices,
    count(cp.condition_price_id) AS condition_price_rows,
    min(cp.provider_observed_at) AS oldest_provider_snapshot,
    max(cp.provider_observed_at) AS newest_provider_snapshot,
    max(cp.loaded_at) AS latest_database_load
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN condition_prices AS cp ON cp.card_id = c.card_id
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT
    s.set_name,
    s.language_code,
    count(*) AS cards_without_condition_prices
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN condition_prices AS cp ON cp.card_id = c.card_id
WHERE cp.condition_price_id IS NULL
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT count(*) AS orphan_condition_price_rows
FROM condition_prices AS cp
LEFT JOIN cards AS c ON c.card_id = cp.card_id
WHERE c.card_id IS NULL;

SELECT count(*) AS duplicate_canonical_groups
FROM (
    SELECT
        card_id,
        source_name,
        currency_code,
        printing,
        condition_name,
        listing_language
    FROM condition_prices
    GROUP BY
        card_id,
        source_name,
        currency_code,
        printing,
        condition_name,
        listing_language
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS condition_price_rows,
    count(*) FILTER (WHERE low_price IS NULL) AS low_nulls,
    count(*) FILTER (WHERE low_price = 0) AS low_zeroes,
    count(*) FILTER (WHERE lowest_with_shipping IS NULL) AS shipping_nulls,
    count(*) FILTER (WHERE lowest_with_shipping = 0) AS shipping_zeroes,
    count(*) FILTER (WHERE median_with_shipping IS NULL) AS median_nulls,
    count(*) FILTER (WHERE median_with_shipping = 0) AS median_zeroes,
    min(sample_count) AS minimum_sample_count,
    max(sample_count) AS maximum_sample_count
FROM condition_prices;

SELECT
    count(*) FILTER (
        WHERE median_with_shipping IS NULL AND sample_count >= 3
    ) AS median_null_with_sample_count_at_least_3,
    count(*) FILTER (
        WHERE median_with_shipping IS NOT NULL AND sample_count < 3
    ) AS median_present_with_sample_count_below_3
FROM condition_prices;

SELECT count(*) AS invalid_numeric_or_timestamp_rows
FROM condition_prices
WHERE low_price < 0
   OR lowest_with_shipping < 0
   OR median_with_shipping < 0
   OR sample_count < 0
   OR loaded_at < provider_observed_at;

SELECT
    source_name,
    currency_code,
    listing_language,
    printing,
    condition_name,
    count(*) AS condition_price_rows
FROM condition_prices
GROUP BY
    source_name,
    currency_code,
    listing_language,
    printing,
    condition_name
ORDER BY
    source_name,
    currency_code,
    listing_language,
    printing,
    condition_name;

SELECT
    (SELECT count(*) FROM cards) AS catalog_cards,
    (SELECT count(*) FROM current_prices) AS current_price_rows_unchanged,
    (SELECT count(*) FROM price_history) AS historical_rows_unchanged;

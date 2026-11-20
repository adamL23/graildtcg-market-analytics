-- Task 6 read-only verification for latest current-price snapshots.

SELECT
    s.set_name,
    s.language_code,
    count(DISTINCT c.card_id) AS catalog_cards,
    count(DISTINCT cp.card_id) AS cards_with_current_price,
    count(cp.current_price_id) AS current_price_rows,
    min(cp.provider_observed_at) AS oldest_provider_snapshot,
    max(cp.provider_observed_at) AS newest_provider_snapshot,
    max(cp.loaded_at) AS latest_database_load
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN current_prices AS cp ON cp.card_id = c.card_id
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT
    s.set_name,
    s.language_code,
    count(*) AS cards_without_current_price
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN current_prices AS cp ON cp.card_id = c.card_id
WHERE cp.current_price_id IS NULL
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT count(*) AS orphan_current_price_rows
FROM current_prices AS cp
LEFT JOIN cards AS c ON c.card_id = cp.card_id
WHERE c.card_id IS NULL;

SELECT count(*) AS duplicate_canonical_groups
FROM (
    SELECT card_id, source_name, currency_code, printing
    FROM current_prices
    GROUP BY card_id, source_name, currency_code, printing
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS current_price_rows,
    count(*) FILTER (WHERE market_price IS NULL) AS market_nulls,
    count(*) FILTER (WHERE market_price = 0) AS market_zeroes,
    count(*) FILTER (WHERE market_price_is_zero) AS flagged_market_zeroes,
    count(*) FILTER (WHERE low_price IS NULL) AS low_nulls,
    count(*) FILTER (WHERE low_price = 0) AS low_zeroes,
    count(*) FILTER (WHERE median_price IS NULL) AS median_nulls,
    count(*) FILTER (WHERE median_price = 0) AS median_zeroes,
    count(*) FILTER (WHERE lowest_with_shipping IS NULL) AS shipping_nulls,
    count(*) FILTER (WHERE lowest_with_shipping = 0) AS shipping_zeroes,
    count(*) FILTER (WHERE no_market_price_since IS NOT NULL) AS stale_market_flags
FROM current_prices;

SELECT count(*) AS invalid_numeric_or_flag_rows
FROM current_prices
WHERE market_price < 0
   OR low_price < 0
   OR median_price < 0
   OR lowest_with_shipping < 0
   OR total_listings < 0
   OR market_price_is_zero IS DISTINCT FROM COALESCE(market_price = 0, FALSE);

SELECT count(*) AS invalid_timestamp_order_rows
FROM current_prices
WHERE no_market_price_since > provider_observed_at
   OR loaded_at < provider_observed_at;

SELECT source_name, currency_code, printing, count(*) AS current_price_rows
FROM current_prices
GROUP BY source_name, currency_code, printing
ORDER BY source_name, currency_code, printing;

SELECT count(*) AS historical_rows_unchanged
FROM price_history;

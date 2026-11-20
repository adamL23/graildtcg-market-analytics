-- Task 5 read-only verification for canonical TCGAPI.dev price history.

SELECT
    s.set_name,
    s.language_code,
    count(DISTINCT c.card_id) AS catalog_cards,
    count(DISTINCT ph.card_id) AS cards_with_history,
    count(ph.price_history_id) AS history_rows,
    min(ph.observation_date) AS first_observation,
    max(ph.observation_date) AS latest_observation
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN price_history AS ph ON ph.card_id = c.card_id
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT
    s.set_name,
    s.language_code,
    count(*) AS cards_without_history
FROM sets AS s
JOIN cards AS c ON c.set_id = s.set_id
LEFT JOIN price_history AS ph ON ph.card_id = c.card_id
WHERE ph.price_history_id IS NULL
GROUP BY s.set_id, s.set_name, s.language_code
ORDER BY s.set_name;

SELECT count(*) AS orphan_history_rows
FROM price_history AS ph
LEFT JOIN cards AS c ON c.card_id = ph.card_id
WHERE c.card_id IS NULL;

SELECT count(*) AS duplicate_canonical_groups
FROM (
    SELECT
        card_id,
        source_name,
        printing,
        currency_code,
        observation_date
    FROM price_history
    GROUP BY
        card_id,
        source_name,
        printing,
        currency_code,
        observation_date
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS history_rows,
    count(*) FILTER (WHERE market_price IS NULL) AS market_nulls,
    count(*) FILTER (WHERE market_price = 0) AS market_zeroes,
    count(*) FILTER (WHERE low_price IS NULL) AS low_nulls,
    count(*) FILTER (WHERE low_price = 0) AS low_zeroes,
    count(*) FILTER (WHERE avg_sales_price IS NULL) AS average_nulls,
    count(*) FILTER (WHERE avg_sales_price = 0) AS average_zeroes,
    count(*) FILTER (WHERE sales_volume IS NULL) AS volume_nulls,
    count(*) FILTER (WHERE sales_volume = 0) AS volume_zeroes
FROM price_history;

SELECT count(*) AS negative_numeric_rows
FROM price_history
WHERE market_price < 0
   OR low_price < 0
   OR avg_sales_price < 0
   OR sales_volume < 0;

SELECT source_name, currency_code, printing, count(*) AS history_rows
FROM price_history
GROUP BY source_name, currency_code, printing
ORDER BY source_name, currency_code, printing;

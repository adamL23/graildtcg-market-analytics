-- Task 9 read-only verification for one completed observation snapshot.

SELECT
    source_snapshot_key,
    count(*) AS observation_rows,
    count(DISTINCT card_id) AS cards_with_observations,
    count(DISTINCT (card_id, printing)) AS card_printing_groups,
    min(sold_date) AS oldest_reported_sold_date,
    max(sold_date) AS newest_reported_sold_date,
    count(*) FILTER (WHERE currency_code IS NULL) AS null_currency_rows,
    count(*) FILTER (WHERE currency_code IS NOT NULL) AS populated_currency_rows,
    count(*) FILTER (WHERE grade_label IS NOT NULL) AS graded_observations,
    count(*) FILTER (WHERE condition_label IS NOT NULL) AS condition_observations
FROM reported_sale_observations
GROUP BY source_snapshot_key
ORDER BY source_snapshot_key;

SELECT count(*) AS duplicate_replay_key_groups
FROM (
    SELECT source_snapshot_key, card_id, printing, source_row_number
    FROM reported_sale_observations
    GROUP BY source_snapshot_key, card_id, printing, source_row_number
    HAVING count(*) > 1
) AS duplicates;

SELECT count(*) AS orphan_observation_rows
FROM reported_sale_observations AS observations
LEFT JOIN cards AS cards ON cards.card_id = observations.card_id
WHERE cards.card_id IS NULL;

SELECT count(*) AS invalid_observation_rows
FROM reported_sale_observations
WHERE btrim(source_snapshot_key) = ''
   OR btrim(printing) = ''
   OR source_row_number <= 0
   OR price < 0
   OR list_price < 0
   OR (currency_code IS NOT NULL AND currency_code !~ '^[A-Z]{3}$')
   OR source_record_hash !~ '^[0-9a-f]{64}$';

SELECT
    (SELECT count(*) FROM cards) AS catalog_cards_unchanged,
    (SELECT count(*) FROM current_prices) AS current_price_rows_unchanged,
    (SELECT count(*) FROM condition_prices) AS condition_price_rows_unchanged,
    (SELECT count(*) FROM graded_price_summaries) AS graded_summary_rows_unchanged,
    (SELECT count(*) FROM price_history) AS historical_rows_unchanged;

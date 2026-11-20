-- Read-only Task 4 catalog checks.

SELECT
    s.set_id,
    s.tcgapi_set_id,
    s.game_name,
    s.set_name,
    s.language_code,
    s.region_code,
    s.release_date,
    count(c.card_id) AS card_rows,
    count(*) FILTER (WHERE c.card_number IS NULL) AS cards_without_number
FROM sets AS s
LEFT JOIN cards AS c
  ON c.set_id = s.set_id
GROUP BY
    s.set_id,
    s.tcgapi_set_id,
    s.game_name,
    s.set_name,
    s.language_code,
    s.region_code,
    s.release_date
ORDER BY s.game_name, s.set_name;

SELECT
    count(*) AS orphan_card_rows
FROM cards AS c
LEFT JOIN sets AS s
  ON s.set_id = c.set_id
WHERE s.set_id IS NULL;

SELECT
    count(*) AS duplicate_provider_set_id_groups
FROM (
    SELECT source_name, tcgapi_set_id
    FROM sets
    WHERE tcgapi_set_id IS NOT NULL
    GROUP BY source_name, tcgapi_set_id
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS duplicate_provider_card_id_groups
FROM (
    SELECT tcgapi_card_id
    FROM cards
    GROUP BY tcgapi_card_id
    HAVING count(*) > 1
) AS duplicates;

SELECT
    count(*) AS card_number_groups_spanning_sets
FROM (
    SELECT card_number
    FROM cards
    WHERE card_number IS NOT NULL
    GROUP BY card_number
    HAVING count(DISTINCT set_id) > 1
) AS repeated_numbers;

SELECT
    count(*) AS price_history_rows
FROM price_history;

SELECT
    source_name,
    count(*) AS set_rows
FROM sets
GROUP BY source_name
ORDER BY source_name;

SELECT
    source_name,
    count(*) AS card_rows
FROM cards
GROUP BY source_name
ORDER BY source_name;


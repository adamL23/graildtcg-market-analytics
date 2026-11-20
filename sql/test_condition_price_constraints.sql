-- Task 7 rollback-only checks for zero, null, and invalid condition values.

BEGIN;

DO $test$
DECLARE
    selected_card_id BIGINT;
    stored_zero NUMERIC;
    stored_null NUMERIC;
BEGIN
    SELECT min(card_id) INTO selected_card_id FROM cards;
    IF selected_card_id IS NULL THEN
        RAISE EXCEPTION 'Task 7 constraint test requires at least one card';
    END IF;

    INSERT INTO condition_prices (
        condition_price_id, card_id, printing, condition_name,
        listing_language, low_price, lowest_with_shipping,
        median_with_shipping, sample_count, provider_observed_at,
        source_name, currency_code, source_file, source_row_number,
        source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        900000000000000101,
        selected_card_id,
        'Task 7 Test',
        'Near Mint',
        'English',
        0,
        0,
        NULL,
        1,
        TIMESTAMPTZ '2000-01-01 00:00:00+00',
        'task7-test',
        'USD',
        'data/raw/test/task7-zero-null.json',
        1,
        repeat('c', 64)
    )
    RETURNING low_price, median_with_shipping INTO stored_zero, stored_null;

    IF stored_zero IS DISTINCT FROM 0 OR stored_null IS NOT NULL THEN
        RAISE EXCEPTION 'Zero or NULL condition price was not preserved';
    END IF;

    BEGIN
        INSERT INTO condition_prices (
            condition_price_id, card_id, printing, condition_name,
            listing_language, low_price, sample_count,
            provider_observed_at, source_name, currency_code, source_file,
            source_row_number, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            900000000000000102,
            selected_card_id,
            'Task 7 Negative Price Test',
            'Near Mint',
            'English',
            -0.01,
            1,
            TIMESTAMPTZ '2000-01-01 00:00:00+00',
            'task7-test',
            'USD',
            'data/raw/test/task7-negative.json',
            1,
            repeat('d', 64)
        );
        RAISE EXCEPTION 'Negative condition price was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO condition_prices (
            condition_price_id, card_id, printing, condition_name,
            listing_language, sample_count, provider_observed_at,
            source_name, currency_code, source_file, source_row_number,
            source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            900000000000000103,
            selected_card_id,
            'Task 7 Negative Sample Test',
            'Near Mint',
            'English',
            -1,
            TIMESTAMPTZ '2000-01-01 00:00:00+00',
            'task7-test',
            'USD',
            'data/raw/test/task7-negative-sample.json',
            1,
            repeat('e', 64)
        );
        RAISE EXCEPTION 'Negative sample count was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$test$;

SELECT
    count(*) FILTER (WHERE low_price = 0) AS synthetic_zero_rows,
    count(*) FILTER (WHERE median_with_shipping IS NULL) AS synthetic_null_rows,
    count(*) FILTER (WHERE low_price < 0 OR sample_count < 0) AS invalid_rows
FROM condition_prices
WHERE source_name = 'task7-test';

ROLLBACK;

-- Task 9 rollback-only checks for replay identity and nullable currency.

BEGIN;

DO $test$
DECLARE
    selected_card_id BIGINT;
BEGIN
    SELECT min(card_id) INTO selected_card_id FROM cards;
    IF selected_card_id IS NULL THEN
        RAISE EXCEPTION 'Task 9 constraint test requires at least one card';
    END IF;

    INSERT INTO reported_sale_observations (
        reported_sale_observation_id, source_snapshot_key, card_id, printing,
        source_row_number, sold_date, price, best_offer, list_price,
        grade_label, condition_label, listing_title, listing_url,
        currency_code, provider_as_of, source_captured_at, source_name,
        source_file, source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        900000000000000301,
        'task9-test:snapshot',
        selected_card_id,
        'Task 9 Test Printing',
        1,
        DATE '2026-01-15',
        12.34,
        FALSE,
        NULL,
        NULL,
        'Near Mint',
        'Exact provider test title',
        'https://example.invalid/item/1',
        NULL,
        DATE '2026-01-31',
        TIMESTAMPTZ '2026-02-01 00:00:00+00',
        'task9-test',
        'data/raw/test/task9.json',
        repeat('a', 64)
    );

    IF NOT EXISTS (
        SELECT 1
        FROM reported_sale_observations
        WHERE source_snapshot_key = 'task9-test:snapshot'
          AND card_id = selected_card_id
          AND printing = 'Task 9 Test Printing'
          AND source_row_number = 1
          AND currency_code IS NULL
    ) THEN
        RAISE EXCEPTION 'Valid observation or nullable currency was not preserved';
    END IF;

    BEGIN
        INSERT INTO reported_sale_observations (
            source_snapshot_key, card_id, printing, source_row_number,
            source_captured_at, source_name, source_file, source_record_hash
        ) VALUES (
            'task9-test:snapshot', selected_card_id, 'Task 9 Test Printing', 1,
            TIMESTAMPTZ '2026-02-01 00:00:00+00', 'task9-test',
            'data/raw/test/task9-duplicate.json', repeat('b', 64)
        );
        RAISE EXCEPTION 'Duplicate replay key was incorrectly accepted';
    EXCEPTION
        WHEN unique_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO reported_sale_observations (
            source_snapshot_key, card_id, printing, source_row_number,
            price, source_captured_at, source_name, source_file,
            source_record_hash
        ) VALUES (
            'task9-test:negative', selected_card_id, 'Task 9 Test Printing', 1,
            -0.01, TIMESTAMPTZ '2026-02-01 00:00:00+00', 'task9-test',
            'data/raw/test/task9-negative.json', repeat('c', 64)
        );
        RAISE EXCEPTION 'Negative observation price was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO reported_sale_observations (
            source_snapshot_key, card_id, printing, source_row_number,
            currency_code, source_captured_at, source_name, source_file,
            source_record_hash
        ) VALUES (
            'task9-test:currency', selected_card_id, 'Task 9 Test Printing', 1,
            'usd', TIMESTAMPTZ '2026-02-01 00:00:00+00', 'task9-test',
            'data/raw/test/task9-currency.json', repeat('d', 64)
        );
        RAISE EXCEPTION 'Invalid currency code was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$test$;

SELECT
    count(*) AS valid_synthetic_rows,
    count(*) FILTER (WHERE currency_code IS NULL) AS null_currency_rows
FROM reported_sale_observations
WHERE source_name = 'task9-test';

ROLLBACK;

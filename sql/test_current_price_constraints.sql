-- Task 6 rollback-only checks for the generated zero flag and price constraints.

BEGIN;

DO $test$
DECLARE
    selected_card_id BIGINT;
    generated_zero_flag BOOLEAN;
BEGIN
    SELECT min(card_id) INTO selected_card_id FROM cards;
    IF selected_card_id IS NULL THEN
        RAISE EXCEPTION 'Task 6 constraint test requires at least one card';
    END IF;

    INSERT INTO current_prices (
        current_price_id, card_id, printing, market_price, total_listings,
        provider_observed_at, source_name, currency_code, source_file,
        source_row_number, source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        900000000000000001,
        selected_card_id,
        'Task 6 Zero Flag Test',
        0,
        0,
        TIMESTAMPTZ '2000-01-01 00:00:00+00',
        'task6-test',
        'USD',
        'data/raw/test/task6-zero.json',
        1,
        repeat('a', 64)
    )
    RETURNING market_price_is_zero INTO generated_zero_flag;

    IF generated_zero_flag IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'A zero market price did not generate a true flag';
    END IF;

    BEGIN
        INSERT INTO current_prices (
            current_price_id, card_id, printing, market_price, total_listings,
            provider_observed_at, source_name, currency_code, source_file,
            source_row_number, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            900000000000000002,
            selected_card_id,
            'Task 6 Negative Price Test',
            -0.01,
            0,
            TIMESTAMPTZ '2000-01-01 00:00:00+00',
            'task6-test',
            'USD',
            'data/raw/test/task6-negative.json',
            1,
            repeat('b', 64)
        );
        RAISE EXCEPTION 'Negative market price was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$test$;

SELECT
    count(*) FILTER (WHERE market_price_is_zero) AS synthetic_zero_flags,
    count(*) FILTER (WHERE market_price < 0) AS synthetic_negative_rows
FROM current_prices
WHERE source_name = 'task6-test';

ROLLBACK;

-- Task 8 rollback-only checks for nullable medians and summary constraints.

BEGIN;

DO $test$
DECLARE
    selected_card_id BIGINT;
    stored_median NUMERIC;
    stored_last_price NUMERIC;
BEGIN
    SELECT min(card_id) INTO selected_card_id FROM cards;
    IF selected_card_id IS NULL THEN
        RAISE EXCEPTION 'Task 8 constraint test requires at least one card';
    END IF;

    INSERT INTO graded_price_summaries (
        graded_price_summary_id, card_id, printing, grade_label,
        median_30d, sales_30d, last_sale_price, last_sold_date,
        ungraded_days, graded_days, provider_as_of,
        is_reported_in_latest_snapshot, coverage_checked_at, source_name,
        currency_code, source_file, source_row_number, source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        900000000000000201,
        selected_card_id,
        'Task 8 Test',
        'PSA 10 Test',
        NULL,
        0,
        100,
        DATE '2026-01-01',
        15,
        30,
        DATE '2026-01-31',
        TRUE,
        TIMESTAMPTZ '2026-02-01 00:00:00+00',
        'task8-test',
        'USD',
        'data/raw/test/task8-null-median.json',
        1,
        repeat('f', 64)
    )
    RETURNING median_30d, last_sale_price
    INTO stored_median, stored_last_price;

    IF stored_median IS NOT NULL OR stored_last_price IS DISTINCT FROM 100 THEN
        RAISE EXCEPTION 'Nullable median and historical last sale were not preserved';
    END IF;

    UPDATE graded_price_summaries
    SET
        is_reported_in_latest_snapshot = FALSE,
        coverage_checked_at = TIMESTAMPTZ '2026-02-02 00:00:00+00'
    WHERE graded_price_summary_id = 900000000000000201;

    IF NOT EXISTS (
        SELECT 1
        FROM graded_price_summaries
        WHERE graded_price_summary_id = 900000000000000201
          AND NOT is_reported_in_latest_snapshot
          AND median_30d IS NULL
          AND last_sale_price = 100
          AND last_sold_date = DATE '2026-01-01'
    ) THEN
        RAISE EXCEPTION 'Last-known transition did not preserve historical sale fields';
    END IF;

    BEGIN
        INSERT INTO graded_price_summaries (
            graded_price_summary_id, card_id, printing, grade_label,
            median_30d, sales_30d, provider_as_of, coverage_checked_at,
            source_name, currency_code, source_file, source_row_number,
            source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            900000000000000202,
            selected_card_id,
            'Task 8 Negative Test',
            'PSA 9 Test',
            -0.01,
            0,
            DATE '2026-01-31',
            TIMESTAMPTZ '2026-02-01 00:00:00+00',
            'task8-test',
            'USD',
            'data/raw/test/task8-negative.json',
            1,
            repeat('1', 64)
        );
        RAISE EXCEPTION 'Negative graded median was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;

    BEGIN
        INSERT INTO graded_price_summaries (
            graded_price_summary_id, card_id, printing, grade_label,
            sales_30d, graded_days, provider_as_of, coverage_checked_at,
            source_name, currency_code, source_file, source_row_number,
            source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            900000000000000203,
            selected_card_id,
            'Task 8 Window Test',
            'PSA 8 Test',
            0,
            31,
            DATE '2026-01-31',
            TIMESTAMPTZ '2026-02-01 00:00:00+00',
            'task8-test',
            'USD',
            'data/raw/test/task8-window.json',
            1,
            repeat('2', 64)
        );
        RAISE EXCEPTION 'Invalid graded_days was incorrectly accepted';
    EXCEPTION
        WHEN check_violation THEN
            NULL;
    END;
END
$test$;

SELECT
    count(*) FILTER (WHERE median_30d IS NULL) AS synthetic_null_medians,
    count(*) FILTER (WHERE last_sale_price IS NOT NULL) AS historical_last_sales,
    count(*) FILTER (
        WHERE NOT is_reported_in_latest_snapshot
    ) AS retained_last_known_rows,
    count(*) FILTER (
        WHERE median_30d < 0 OR graded_days > 30
    ) AS invalid_rows
FROM graded_price_summaries
WHERE source_name = 'task8-test';

ROLLBACK;

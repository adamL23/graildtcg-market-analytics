-- Transactional synthetic tests for the Phase 1 normalized schema.
-- Fixed identity values avoid advancing the real identity sequences.
-- Every successful test is rolled back at the end of this file.

BEGIN;

CREATE TEMP TABLE constraint_test_results (
    test_name TEXT PRIMARY KEY,
    passed BOOLEAN NOT NULL,
    detail TEXT NOT NULL
) ON COMMIT DROP;

DO $test$
DECLARE
    primary_set_id CONSTANT BIGINT := 9000000001;
    secondary_set_id CONSTANT BIGINT := 9000000002;
    regional_set_id CONSTANT BIGINT := 9000000003;
    primary_card_id CONSTANT BIGINT := 9100000001;
    caught_expected_error BOOLEAN;
    matching_rows BIGINT;
    revised_market_price NUMERIC(12, 2);
    revised_hash TEXT;
BEGIN
    INSERT INTO sets (
        set_id, tcgapi_set_id, source_set_key, game_id, game_name,
        set_name, set_code, language_code, region_code, release_date,
        source_name, source_observed_at
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        primary_set_id, 9000000001, 'synthetic:release:en:intl', 55,
        'Synthetic Game', 'Synthetic Set', 'SYN', 'en', 'INTL',
        DATE '2098-12-01', 'schema-test', CURRENT_TIMESTAMP
    );
    INSERT INTO constraint_test_results
    VALUES ('valid set insertion', TRUE, 'Accepted a complete provider-backed set.');

    INSERT INTO sets (
        set_id, tcgapi_set_id, source_set_key, game_id, game_name,
        set_name, set_code, language_code, region_code, source_name
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        secondary_set_id, NULL, 'synthetic:release:ja:jp', 55,
        'Synthetic Game', 'Synthetic Japanese Set', NULL, 'ja', 'JP',
        'schema-test'
    );
    INSERT INTO constraint_test_results
    VALUES ('fallback set identity', TRUE, 'Accepted a stable source_set_key with no provider set ID.');

    INSERT INTO sets (
        set_id, tcgapi_set_id, source_set_key, game_id, game_name,
        set_name, set_code, language_code, region_code, source_name
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        regional_set_id, NULL, 'synthetic:release:en:asia', 55,
        'Synthetic Game', 'Synthetic Set', 'SYN', 'en', 'ASIA',
        'schema-test'
    );

    SELECT count(*)
    INTO matching_rows
    FROM sets
    WHERE game_id = 55
      AND set_name = 'Synthetic Set'
      AND language_code = 'en'
      AND region_code IN ('INTL', 'ASIA');
    IF matching_rows <> 2 THEN
        RAISE EXCEPTION 'Language and region separation test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('language and region separation', TRUE, 'Preserved one language across two explicitly keyed regional releases.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO sets (
            set_id, tcgapi_set_id, source_set_key, game_id, game_name,
            set_name, language_code, source_name
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9000000101, 9000000001, 'synthetic:other-provider-key', 55,
            'Synthetic Game', 'Duplicate Provider Set', 'en', 'schema-test'
        );
    EXCEPTION WHEN unique_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Duplicate provider set identity test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('duplicate provider set identity', TRUE, 'Rejected a duplicate non-null provider set ID in the source namespace.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO sets (
            set_id, tcgapi_set_id, source_set_key, game_id, game_name,
            set_name, language_code, source_name
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9000000102, NULL, 'synthetic:release:ja:jp', 55,
            'Synthetic Game', 'Duplicate Fallback Set', 'ja', 'schema-test'
        );
    EXCEPTION WHEN unique_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Duplicate fallback set identity test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('duplicate fallback set identity', TRUE, 'Rejected a duplicate source_set_key in the source namespace.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO sets (
            set_id, tcgapi_set_id, source_set_key, game_id, game_name,
            set_name, language_code, region_code, source_name
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9000000103, NULL, 'synthetic:invalid:language', 55,
            'Synthetic Game', 'Invalid Language Set', 'en-US', NULL,
            'schema-test'
        );
    EXCEPTION WHEN check_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Language/region interchange test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('language code validation', TRUE, 'Rejected a region embedded in language_code; region_code is separate.');

    INSERT INTO cards (
        card_id, tcgapi_card_id, tcgplayer_id, card_name, card_number,
        rarity, variant_name, image_url, source_name, source_file,
        source_observed_at, set_id
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        primary_card_id, 9100000001, 9100000001, 'Synthetic Card',
        'TEST-001', 'Test Rare', NULL, NULL, 'schema-test', NULL,
        CURRENT_TIMESTAMP, primary_set_id
    );
    INSERT INTO constraint_test_results
    VALUES ('valid card insertion', TRUE, 'Accepted a card referencing the internal set identity.');

    INSERT INTO cards (
        card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9100000002, 9100000002, 'Second Synthetic Card', 'TEST-002',
        'schema-test', primary_set_id
    );

    SELECT count(*)
    INTO matching_rows
    FROM cards
    WHERE set_id = primary_set_id;
    IF matching_rows <> 2 THEN
        RAISE EXCEPTION 'Set-to-many-cards relationship test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('set contains multiple cards', TRUE, 'Accepted two distinct cards in one set.');

    INSERT INTO cards (
        card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9100000003, 9100000003, 'Same Number, Other Set', 'TEST-001',
        'schema-test', secondary_set_id
    );

    SELECT count(*)
    INTO matching_rows
    FROM cards
    WHERE card_number = 'TEST-001'
      AND set_id IN (primary_set_id, secondary_set_id);
    IF matching_rows <> 2 THEN
        RAISE EXCEPTION 'Identical card numbers across sets test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('identical numbers across sets', TRUE, 'Accepted the same card number in two different sets.');

    INSERT INTO cards (
        card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9100000004, 9100000004, 'Card Without Provider Number', NULL,
        'schema-test', primary_set_id
    );
    INSERT INTO constraint_test_results
    VALUES ('nullable card number', TRUE, 'Accepted a valid provider card without a collector number.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO cards (
            card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9100000101, 9100000101, 'Invalid Set Reference', 'TEST-101',
            'schema-test', 9999999999
        );
    EXCEPTION WHEN foreign_key_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Invalid set reference test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('invalid set reference', TRUE, 'Rejected a card referencing a nonexistent set.');

    INSERT INTO price_history (
        price_history_id, card_id, observation_date, printing,
        market_price, low_price, avg_sales_price, sales_volume,
        source_name, currency_code, source_file, source_row_number,
        source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9200000001, primary_card_id, DATE '2099-01-01', 'Foil',
        10.25, 9.00, 10.00, 2, 'schema-test', 'USD', NULL, NULL,
        repeat('a', 64)
    );
    INSERT INTO constraint_test_results
    VALUES ('valid price insertion', TRUE, 'Accepted a canonical observation for the referenced card.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO price_history (
            price_history_id, card_id, observation_date, printing,
            market_price, source_name, currency_code, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9200000002, 9999999999, DATE '2099-01-02', 'Foil',
            10.00, 'schema-test', 'USD', repeat('b', 64)
        );
    EXCEPTION WHEN foreign_key_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Price foreign-key enforcement test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('price foreign-key enforcement', TRUE, 'Rejected a price row for a nonexistent card.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO price_history (
            price_history_id, card_id, observation_date, printing,
            market_price, source_name, currency_code, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9200000003, primary_card_id, DATE '2099-01-01', 'Foil',
            11.00, 'schema-test', 'USD', repeat('c', 64)
        );
    EXCEPTION WHEN unique_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Canonical duplicate handling test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('duplicate price handling', TRUE, 'Rejected a second row with the same canonical observation key.');

    INSERT INTO price_history (
        price_history_id, card_id, observation_date, printing,
        market_price, low_price, avg_sales_price, sales_volume,
        source_name, currency_code, source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9200000004, primary_card_id, DATE '2099-01-01', 'Foil',
        12.75, 10.00, 12.00, 3, 'schema-test', 'USD', repeat('d', 64)
    )
    ON CONFLICT ON CONSTRAINT uq_price_history_canonical_observation
    DO UPDATE SET
        market_price = EXCLUDED.market_price,
        low_price = EXCLUDED.low_price,
        avg_sales_price = EXCLUDED.avg_sales_price,
        sales_volume = EXCLUDED.sales_volume,
        source_record_hash = EXCLUDED.source_record_hash,
        loaded_at = CURRENT_TIMESTAMP;

    SELECT count(*), max(market_price), max(source_record_hash)
    INTO matching_rows, revised_market_price, revised_hash
    FROM price_history
    WHERE card_id = primary_card_id
      AND source_name = 'schema-test'
      AND printing = 'Foil'
      AND currency_code = 'USD'
      AND observation_date = DATE '2099-01-01';
    IF matching_rows <> 1
       OR revised_market_price <> 12.75
       OR revised_hash <> repeat('d', 64) THEN
        RAISE EXCEPTION 'Revised historical observation test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('revised historical observation', TRUE, 'Upsert updated one canonical row and replaced its content hash.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO price_history (
            price_history_id, card_id, observation_date, printing,
            market_price, source_name, currency_code, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9200000005, primary_card_id, DATE '2099-01-03', 'Foil',
            -0.01, 'schema-test', 'USD', repeat('e', 64)
        );
    EXCEPTION WHEN check_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Negative price rejection test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('negative price rejection', TRUE, 'Rejected a negative market price.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO cards (
            card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9100000102, 0, 'Invalid Provider ID', 'TEST-102',
            'schema-test', primary_set_id
        );
    EXCEPTION WHEN check_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Invalid provider identifier test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('invalid provider identifier', TRUE, 'Rejected a nonpositive TCG API card ID.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO cards (
            card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            0, 9100000103, 'Invalid Internal ID', 'TEST-103',
            'schema-test', primary_set_id
        );
    EXCEPTION WHEN check_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Invalid internal identifier test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('invalid internal identifier', TRUE, 'Rejected a nonpositive internal card ID.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO cards (
            card_id, tcgapi_card_id, card_name, card_number, source_name, set_id
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9100000104, 9100000104, NULL, 'TEST-104',
            'schema-test', primary_set_id
        );
    EXCEPTION WHEN not_null_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Missing required value test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('missing required value', TRUE, 'Rejected a card without card_name.');

    caught_expected_error := FALSE;
    BEGIN
        INSERT INTO price_history (
            price_history_id, card_id, observation_date, printing,
            market_price, source_name, currency_code, source_record_hash
        ) OVERRIDING SYSTEM VALUE
        VALUES (
            9200000006, primary_card_id, DATE '2099-01-04', 'Foil',
            1.00, 'schema-test', 'usd', repeat('f', 64)
        );
    EXCEPTION WHEN check_violation THEN
        caught_expected_error := TRUE;
    END;
    IF NOT caught_expected_error THEN
        RAISE EXCEPTION 'Currency code validation test failed';
    END IF;
    INSERT INTO constraint_test_results
    VALUES ('currency code validation', TRUE, 'Rejected a non-uppercase three-letter currency code.');

    INSERT INTO price_history (
        price_history_id, card_id, observation_date, printing,
        market_price, low_price, avg_sales_price, sales_volume,
        source_name, currency_code, source_file, source_row_number,
        source_record_hash
    ) OVERRIDING SYSTEM VALUE
    VALUES (
        9200000007, primary_card_id, DATE '2099-01-05', 'Foil',
        NULL, NULL, NULL, NULL, 'schema-test', 'USD', NULL, NULL,
        repeat('1', 64)
    );
    INSERT INTO constraint_test_results
    VALUES ('nullable pricing values', TRUE, 'Accepted NULL prices and sales volume without converting them to zero.');
END
$test$;

SELECT test_name, passed, detail
FROM constraint_test_results
ORDER BY test_name;

ROLLBACK;


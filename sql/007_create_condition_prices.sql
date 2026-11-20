-- Task 7: latest provider-reported listing prices by condition.

BEGIN;

CREATE TABLE condition_prices (
    condition_price_id BIGINT GENERATED ALWAYS AS IDENTITY,
    card_id BIGINT NOT NULL,
    printing TEXT NOT NULL,
    condition_name TEXT NOT NULL,
    listing_language TEXT NOT NULL,
    low_price NUMERIC(30, 16),
    lowest_with_shipping NUMERIC(30, 16),
    median_with_shipping NUMERIC(30, 16),
    sample_count INTEGER NOT NULL,
    provider_observed_at TIMESTAMPTZ NOT NULL,
    source_name TEXT NOT NULL,
    currency_code CHAR(3) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_hash CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_condition_prices PRIMARY KEY (condition_price_id),
    CONSTRAINT fk_condition_prices_card
        FOREIGN KEY (card_id)
        REFERENCES cards (card_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT uq_condition_prices_canonical_snapshot
        UNIQUE (
            card_id,
            source_name,
            currency_code,
            printing,
            condition_name,
            listing_language
        ),
    CONSTRAINT chk_condition_prices_id_positive
        CHECK (condition_price_id > 0),
    CONSTRAINT chk_condition_prices_card_id_positive
        CHECK (card_id > 0),
    CONSTRAINT chk_condition_prices_printing_not_blank
        CHECK (btrim(printing) <> ''),
    CONSTRAINT chk_condition_prices_condition_not_blank
        CHECK (btrim(condition_name) <> ''),
    CONSTRAINT chk_condition_prices_language_not_blank
        CHECK (btrim(listing_language) <> ''),
    CONSTRAINT chk_condition_prices_low_nonnegative
        CHECK (low_price IS NULL OR low_price >= 0),
    CONSTRAINT chk_condition_prices_shipping_nonnegative
        CHECK (lowest_with_shipping IS NULL OR lowest_with_shipping >= 0),
    CONSTRAINT chk_condition_prices_median_nonnegative
        CHECK (median_with_shipping IS NULL OR median_with_shipping >= 0),
    CONSTRAINT chk_condition_prices_sample_count_nonnegative
        CHECK (sample_count >= 0),
    CONSTRAINT chk_condition_prices_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    CONSTRAINT chk_condition_prices_currency_code
        CHECK (currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT chk_condition_prices_source_file_not_blank
        CHECK (btrim(source_file) <> ''),
    CONSTRAINT chk_condition_prices_source_row_positive
        CHECK (source_row_number > 0),
    CONSTRAINT chk_condition_prices_source_hash_sha256
        CHECK (source_record_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_condition_prices_card_id
    ON condition_prices (card_id);

CREATE INDEX idx_condition_prices_provider_observed_at
    ON condition_prices (provider_observed_at);

COMMENT ON TABLE condition_prices IS
    'Latest provider-reported listing-price snapshot per card, printing, condition, language, source and currency.';

COMMENT ON COLUMN condition_prices.condition_name IS
    'Provider condition label retained as text; live data includes Unopened in addition to standard card conditions.';

COMMENT ON COLUMN condition_prices.listing_language IS
    'Provider listing language, such as English or Japanese; distinct from set language metadata.';

COMMENT ON COLUMN condition_prices.median_with_shipping IS
    'Provider median of sampled shipping-inclusive listings; normally null when sample_count is below three.';

COMMENT ON COLUMN condition_prices.sample_count IS
    'Number of provider-sampled listings, not total market depth.';

COMMENT ON COLUMN condition_prices.provider_observed_at IS
    'Provider last_updated_at timestamp used to order competing snapshots.';

COMMENT ON COLUMN condition_prices.loaded_at IS
    'Database ingestion timestamp, distinct from provider_observed_at.';

COMMIT;

-- Task 6: latest provider-reported current price per canonical printing.

BEGIN;

CREATE TABLE current_prices (
    current_price_id BIGINT GENERATED ALWAYS AS IDENTITY,
    card_id BIGINT NOT NULL,
    printing TEXT NOT NULL,
    market_price NUMERIC(30, 16),
    low_price NUMERIC(30, 16),
    median_price NUMERIC(30, 16),
    lowest_with_shipping NUMERIC(30, 16),
    total_listings INTEGER NOT NULL,
    market_price_as_of DATE,
    provider_observed_at TIMESTAMPTZ NOT NULL,
    no_market_price_since TIMESTAMPTZ,
    market_price_is_zero BOOLEAN GENERATED ALWAYS AS (
        COALESCE(market_price = 0, FALSE)
    ) STORED,
    source_name TEXT NOT NULL,
    currency_code CHAR(3) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_hash CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_current_prices PRIMARY KEY (current_price_id),
    CONSTRAINT fk_current_prices_card
        FOREIGN KEY (card_id)
        REFERENCES cards (card_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT uq_current_prices_canonical_snapshot
        UNIQUE (card_id, source_name, currency_code, printing),
    CONSTRAINT chk_current_prices_id_positive
        CHECK (current_price_id > 0),
    CONSTRAINT chk_current_prices_card_id_positive
        CHECK (card_id > 0),
    CONSTRAINT chk_current_prices_printing_not_blank
        CHECK (btrim(printing) <> ''),
    CONSTRAINT chk_current_prices_market_nonnegative
        CHECK (market_price IS NULL OR market_price >= 0),
    CONSTRAINT chk_current_prices_low_nonnegative
        CHECK (low_price IS NULL OR low_price >= 0),
    CONSTRAINT chk_current_prices_median_nonnegative
        CHECK (median_price IS NULL OR median_price >= 0),
    CONSTRAINT chk_current_prices_shipping_nonnegative
        CHECK (lowest_with_shipping IS NULL OR lowest_with_shipping >= 0),
    CONSTRAINT chk_current_prices_listings_nonnegative
        CHECK (total_listings >= 0),
    CONSTRAINT chk_current_prices_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    CONSTRAINT chk_current_prices_currency_code
        CHECK (currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT chk_current_prices_source_file_not_blank
        CHECK (btrim(source_file) <> ''),
    CONSTRAINT chk_current_prices_source_row_positive
        CHECK (source_row_number > 0),
    CONSTRAINT chk_current_prices_source_hash_sha256
        CHECK (source_record_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_current_prices_no_market_price_timing
        CHECK (
            no_market_price_since IS NULL
            OR no_market_price_since <= provider_observed_at
        )
);

CREATE INDEX idx_current_prices_card_id
    ON current_prices (card_id);

CREATE INDEX idx_current_prices_provider_observed_at
    ON current_prices (provider_observed_at);

COMMENT ON TABLE current_prices IS
    'Latest provider-reported ungraded current-price snapshot per card, source, currency and printing.';

COMMENT ON COLUMN current_prices.market_price_as_of IS
    'Provider date for the reported market price; it may be older than the overall price snapshot.';

COMMENT ON COLUMN current_prices.provider_observed_at IS
    'Provider price_updated_at timestamp used to order competing snapshots.';

COMMENT ON COLUMN current_prices.loaded_at IS
    'Database ingestion timestamp, distinct from provider_observed_at.';

COMMENT ON COLUMN current_prices.market_price_is_zero IS
    'Analytical flag only; true preserves and identifies a provider-reported zero without treating it as a genuine zero-dollar valuation.';

COMMENT ON COLUMN current_prices.source_record_hash IS
    'SHA-256 of the normalized provider snapshot for same-timestamp revision detection.';

COMMIT;

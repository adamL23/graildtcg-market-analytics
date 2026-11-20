-- Phase 1 core schema.
-- The Python runner applies this entire file in one transaction.

CREATE TABLE cards (
    card_id BIGINT GENERATED ALWAYS AS IDENTITY,
    tcgapi_card_id BIGINT NOT NULL,
    tcgplayer_id BIGINT,
    game_id BIGINT NOT NULL,
    game_name TEXT NOT NULL,
    game_slug TEXT,
    set_id BIGINT NOT NULL,
    set_name TEXT NOT NULL,
    card_name TEXT NOT NULL,
    card_number TEXT NOT NULL,
    rarity TEXT,
    variant_name TEXT,
    image_url TEXT,
    source_file TEXT NOT NULL,
    source_observed_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_cards PRIMARY KEY (card_id),
    CONSTRAINT uq_cards_tcgapi_card_id UNIQUE (tcgapi_card_id),
    CONSTRAINT chk_cards_tcgapi_card_id_positive CHECK (tcgapi_card_id > 0),
    CONSTRAINT chk_cards_game_id_positive CHECK (game_id > 0),
    CONSTRAINT chk_cards_set_id_positive CHECK (set_id > 0),
    CONSTRAINT chk_cards_name_not_blank CHECK (btrim(card_name) <> ''),
    CONSTRAINT chk_cards_number_not_blank CHECK (btrim(card_number) <> ''),
    CONSTRAINT chk_cards_source_file_not_blank CHECK (btrim(source_file) <> '')
);

CREATE TABLE price_history (
    price_history_id BIGINT GENERATED ALWAYS AS IDENTITY,
    card_id BIGINT NOT NULL,
    observation_date DATE NOT NULL,
    printing TEXT NOT NULL,
    market_price NUMERIC(12, 2),
    low_price NUMERIC(12, 2),
    avg_sales_price NUMERIC(12, 2),
    sales_volume INTEGER,
    source_file TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    source_record_hash TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_price_history PRIMARY KEY (price_history_id),
    CONSTRAINT fk_price_history_card
        FOREIGN KEY (card_id)
        REFERENCES cards (card_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT uq_price_history_card_source_hash
        UNIQUE (card_id, source_record_hash),
    CONSTRAINT chk_price_history_printing_not_blank
        CHECK (btrim(printing) <> ''),
    CONSTRAINT chk_price_history_market_price_nonnegative
        CHECK (market_price IS NULL OR market_price >= 0),
    CONSTRAINT chk_price_history_low_price_nonnegative
        CHECK (low_price IS NULL OR low_price >= 0),
    CONSTRAINT chk_price_history_avg_sales_price_nonnegative
        CHECK (avg_sales_price IS NULL OR avg_sales_price >= 0),
    CONSTRAINT chk_price_history_sales_volume_nonnegative
        CHECK (sales_volume IS NULL OR sales_volume >= 0),
    CONSTRAINT chk_price_history_source_file_not_blank
        CHECK (btrim(source_file) <> ''),
    CONSTRAINT chk_price_history_source_row_number_positive
        CHECK (source_row_number > 0),
    CONSTRAINT chk_price_history_source_record_hash_sha256
        CHECK (
            length(source_record_hash) = 64
            AND source_record_hash ~ '^[0-9a-f]{64}$'
        )
);

CREATE INDEX idx_price_history_card_date
    ON price_history (card_id, observation_date);

CREATE INDEX idx_price_history_card_printing_date
    ON price_history (card_id, printing, observation_date);

COMMENT ON TABLE cards IS
    'Canonical card identity from TCG API; one row per TCG API card ID.';

COMMENT ON TABLE price_history IS
    'Dated provider observations. Null values remain null and repeated dates are permitted.';

COMMENT ON COLUMN price_history.source_record_hash IS
    'SHA-256 of the normalized source observation, used for idempotent loading.';


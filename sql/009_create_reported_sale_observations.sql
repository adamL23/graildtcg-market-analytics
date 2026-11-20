-- Task 9: immutable provider-returned sale observations, not verified transactions.

BEGIN;

CREATE TABLE reported_sale_observations (
    reported_sale_observation_id BIGINT GENERATED ALWAYS AS IDENTITY,
    source_snapshot_key TEXT NOT NULL,
    card_id BIGINT NOT NULL,
    printing TEXT NOT NULL,
    source_row_number INTEGER NOT NULL,
    sold_date DATE,
    price NUMERIC(30, 16),
    best_offer BOOLEAN,
    list_price NUMERIC(30, 16),
    grade_label TEXT,
    condition_label TEXT,
    listing_title TEXT,
    listing_url TEXT,
    currency_code CHAR(3),
    provider_as_of DATE,
    source_captured_at TIMESTAMPTZ NOT NULL,
    source_name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_record_hash CHAR(64) NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_reported_sale_observations
        PRIMARY KEY (reported_sale_observation_id),
    CONSTRAINT fk_reported_sale_observations_card
        FOREIGN KEY (card_id)
        REFERENCES cards (card_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CONSTRAINT uq_reported_sale_observations_replay_key
        UNIQUE (source_snapshot_key, card_id, printing, source_row_number),
    CONSTRAINT chk_reported_sale_observations_id_positive
        CHECK (reported_sale_observation_id > 0),
    CONSTRAINT chk_reported_sale_observations_snapshot_not_blank
        CHECK (btrim(source_snapshot_key) <> ''),
    CONSTRAINT chk_reported_sale_observations_card_id_positive
        CHECK (card_id > 0),
    CONSTRAINT chk_reported_sale_observations_printing_not_blank
        CHECK (btrim(printing) <> ''),
    CONSTRAINT chk_reported_sale_observations_source_row_positive
        CHECK (source_row_number > 0),
    CONSTRAINT chk_reported_sale_observations_price_nonnegative
        CHECK (price IS NULL OR price >= 0),
    CONSTRAINT chk_reported_sale_observations_list_price_nonnegative
        CHECK (list_price IS NULL OR list_price >= 0),
    CONSTRAINT chk_reported_sale_observations_currency_code
        CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT chk_reported_sale_observations_source_name_not_blank
        CHECK (btrim(source_name) <> ''),
    CONSTRAINT chk_reported_sale_observations_source_file_not_blank
        CHECK (btrim(source_file) <> ''),
    CONSTRAINT chk_reported_sale_observations_source_hash_sha256
        CHECK (source_record_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_reported_sale_observations_snapshot
    ON reported_sale_observations (source_snapshot_key);

CREATE INDEX idx_reported_sale_observations_card_id
    ON reported_sale_observations (card_id);

CREATE INDEX idx_reported_sale_observations_sold_date
    ON reported_sale_observations (sold_date);

COMMENT ON TABLE reported_sale_observations IS
    'Immutable provider-returned sale observations from one extraction snapshot; rows are not verified globally unique transactions.';

COMMENT ON COLUMN reported_sale_observations.source_snapshot_key IS
    'Immutable extraction identity retained unchanged by every offline replay.';

COMMENT ON COLUMN reported_sale_observations.source_row_number IS
    'Deterministic one-based position inside the source card-and-printing sales array.';

COMMENT ON COLUMN reported_sale_observations.currency_code IS
    'Nullable because the verified Task 9 response supplies no sale currency; never inferred from provider, URL, or subscription.';

COMMENT ON COLUMN reported_sale_observations.provider_as_of IS
    'Provider ebay.as_of date for the parent printing summary, not a sale event timestamp.';

COMMENT ON COLUMN reported_sale_observations.source_captured_at IS
    'Timestamp when the exact card response was captured by the extractor.';

COMMENT ON COLUMN reported_sale_observations.source_record_hash IS
    'Hash of the replay identity and exact normalized provider observation; a conflicting hash for the same replay key is an integrity error.';

COMMIT;
